"""SootheRunner -- protocol-orchestrated agent runner (RFC-0003).

Wraps `create_soothe_agent()` with protocol pre/post-processing and
yields the deepagents-canonical ``(namespace, mode, data)`` stream
extended with ``soothe.*`` custom events for protocol observability.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from langchain_core.messages import HumanMessage
from langgraph.types import Command, Interrupt

from soothe.config import SootheConfig
from soothe.protocols.context import ContextEntry, ContextProjection, ContextProtocol
from soothe.protocols.planner import Plan, PlanContext, PlannerProtocol, StepResult
from soothe.protocols.policy import ActionRequest, PolicyContext, PolicyProtocol

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    from langgraph.graph.state import CompiledStateGraph

    from soothe.protocols.memory import MemoryItem, MemoryProtocol

logger = logging.getLogger(__name__)

StreamChunk = tuple[tuple[str, ...], str, Any]
"""Deepagents-canonical stream chunk: ``(namespace, mode, data)``."""

_STREAM_CHUNK_LEN = 3
_MSG_PAIR_LEN = 2
_MAX_HITL_ITERATIONS = 50


def _custom(data: dict[str, Any]) -> StreamChunk:
    """Build a soothe protocol custom event chunk."""
    return ((), "custom", data)


def _generate_thread_id() -> str:
    """Generate an 8-char hex thread ID (matching deepagents convention)."""
    return uuid.uuid4().hex[:8]


# ---------------------------------------------------------------------------
# Runner state
# ---------------------------------------------------------------------------


@dataclass
class RunnerState:
    """Mutable state accumulated during a single query execution."""

    thread_id: str = ""
    full_response: list[str] = field(default_factory=list)
    plan: Plan | None = None
    context_projection: ContextProjection | None = None
    recalled_memories: list[MemoryItem] = field(default_factory=list)
    seen_message_ids: set[str] = field(default_factory=set)


# ---------------------------------------------------------------------------
# SootheRunner
# ---------------------------------------------------------------------------


class SootheRunner:
    """Protocol-orchestrated agent runner.

    Wraps ``create_soothe_agent()`` with pre/post protocol steps and
    provides ``astream()`` that yields the deepagents-canonical stream
    format extended with ``soothe.*`` protocol custom events.

    Args:
        config: Soothe configuration. If ``None``, uses defaults.
    """

    def __init__(self, config: SootheConfig | None = None) -> None:  # noqa: D107
        from langgraph.checkpoint.memory import MemorySaver

        from soothe.backends.durability.in_memory import InMemoryDurability
        from soothe.core.agent import create_soothe_agent

        self._config = config or SootheConfig()
        self._checkpointer = MemorySaver()
        self._agent: CompiledStateGraph = create_soothe_agent(
            self._config,
            checkpointer=self._checkpointer,
        )

        self._context: ContextProtocol | None = getattr(self._agent, "soothe_context", None)
        self._memory: MemoryProtocol | None = getattr(self._agent, "soothe_memory", None)
        self._planner: PlannerProtocol | None = getattr(self._agent, "soothe_planner", None)
        self._policy: PolicyProtocol | None = getattr(self._agent, "soothe_policy", None)
        self._durability = InMemoryDurability()
        self._current_thread_id: str | None = None
        self._current_plan: Plan | None = None

    # -- public helpers -----------------------------------------------------

    @property
    def config(self) -> SootheConfig:
        """The active configuration."""
        return self._config

    @property
    def current_thread_id(self) -> str | None:
        """Thread ID for the active session, or ``None``."""
        return self._current_thread_id

    @property
    def current_plan(self) -> Plan | None:
        """The current plan, or ``None``."""
        return self._current_plan

    def set_current_thread_id(self, thread_id: str | None) -> None:
        """Set the active thread ID used by future runs.

        Args:
            thread_id: Thread ID to reuse, or ``None`` to clear.
        """
        self._current_thread_id = thread_id

    def protocol_summary(self) -> dict[str, str]:
        """Return a summary of active protocol implementations."""
        return {
            "context": type(self._context).__name__ if self._context else "none",
            "memory": type(self._memory).__name__ if self._memory else "none",
            "planner": type(self._planner).__name__ if self._planner else "none",
            "policy": type(self._policy).__name__ if self._policy else "none",
            "durability": type(self._durability).__name__,
        }

    async def context_stats(self) -> dict[str, Any]:
        """Return context statistics for the /context slash command."""
        if not self._context:
            return {"status": "disabled"}
        entries = getattr(self._context, "entries", [])
        return {
            "status": "active",
            "backend": type(self._context).__name__,
            "entries": len(entries) if isinstance(entries, list) else "unknown",
        }

    async def memory_stats(self) -> dict[str, Any]:
        """Return memory statistics for the /memory slash command."""
        if not self._memory:
            return {"status": "disabled"}
        return {
            "status": "active",
            "backend": type(self._memory).__name__,
        }

    async def list_threads(self) -> list[dict[str, Any]]:
        """List all threads via DurabilityProtocol."""
        threads = await self._durability.list_threads()
        return [t.model_dump() for t in threads]

    async def cleanup(self) -> None:
        """Clean up resources during shutdown.

        Stops background indexer tasks and closes connection pools.
        """
        # Check for skillify indexer in subagents
        if hasattr(self._agent, "subagents"):
            for subagent in getattr(self._agent, "subagents", []):
                if isinstance(subagent, dict) and "_skillify_indexer" in subagent:
                    indexer = subagent["_skillify_indexer"]
                    try:
                        await indexer.stop()
                    except Exception:
                        logger.debug("Failed to stop skillify indexer", exc_info=True)

    # -- main stream --------------------------------------------------------

    async def astream(
        self,
        user_input: str,
        *,
        thread_id: str | None = None,
    ) -> AsyncGenerator[StreamChunk, None]:
        """Stream agent execution with protocol orchestration.

        Yields ``(namespace, mode, data)`` tuples in the deepagents-canonical
        format.  Protocol events are emitted as ``custom`` events with
        ``soothe.*`` type prefix.

        Args:
            user_input: The user's query text.
            thread_id: Thread ID for persistence. Generated if not provided.
        """
        state = RunnerState()
        state.thread_id = thread_id or self._current_thread_id or ""
        self._current_thread_id = state.thread_id or None

        # ---- Phase 1: pre-stream protocol orchestration -------------------

        async for chunk in self._pre_stream(user_input, state):
            yield chunk

        # ---- Phase 2: LangGraph stream with HITL loop --------------------

        enriched_messages = self._build_enriched_input(
            user_input,
            state.context_projection,
            state.recalled_memories,
        )
        stream_input: dict[str, Any] | Command = {"messages": enriched_messages}
        config = {"configurable": {"thread_id": thread_id}}

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
                yield _custom({"type": "soothe.error", "error": str(exc)})
                break

            if not interrupt_occurred:
                break

            hitl_iterations += 1
            if hitl_iterations > _MAX_HITL_ITERATIONS:
                logger.warning("Exceeded HITL iteration limit (%d)", _MAX_HITL_ITERATIONS)
                yield _custom(
                    {
                        "type": "soothe.error",
                        "error": f"Exceeded {_MAX_HITL_ITERATIONS} HITL iterations",
                    }
                )
                break

            resume_payload = self._auto_approve(pending_interrupts)
            stream_input = Command(resume=resume_payload)

        # ---- Phase 3: post-stream protocol orchestration ------------------

        async for chunk in self._post_stream(user_input, state):
            yield chunk

    # -- phase helpers ------------------------------------------------------

    async def _pre_stream(
        self,
        user_input: str,
        state: RunnerState,
    ) -> AsyncGenerator[StreamChunk, None]:
        """Run protocol pre-processing before the LangGraph stream."""
        from soothe.protocols.durability import ThreadMetadata

        # Thread management
        requested_thread_id = state.thread_id
        try:
            thread_info = None
            if requested_thread_id:
                thread_info = await self._durability.resume_thread(requested_thread_id)
                yield _custom({"type": "soothe.thread.resumed", "thread_id": thread_info.thread_id})
            else:
                thread_info = await self._durability.create_thread(
                    ThreadMetadata(policy_profile=self._config.policy_profile),
                )
                yield _custom({"type": "soothe.thread.created", "thread_id": thread_info.thread_id})
            state.thread_id = thread_info.thread_id
            self._current_thread_id = thread_info.thread_id
        except KeyError:
            logger.debug("Thread resume failed, creating a new thread", exc_info=True)
            try:
                thread_info = await self._durability.create_thread(
                    ThreadMetadata(policy_profile=self._config.policy_profile),
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

        # Context restoration (when resuming a thread)
        if self._context and hasattr(self._context, "restore") and requested_thread_id:
            try:
                restored = await self._context.restore(state.thread_id)
                if restored:
                    logger.info("Context restored for thread %s", state.thread_id)
            except Exception:
                logger.debug("Context restore failed", exc_info=True)

        protocols = self.protocol_summary()
        yield _custom(
            {
                "type": "soothe.session.started",
                "thread_id": state.thread_id,
                "protocols": protocols,
            }
        )

        # Policy check
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
                    }
                )
                if decision.verdict == "deny":
                    yield _custom(
                        {
                            "type": "soothe.policy.denied",
                            "action": "user_request",
                            "reason": decision.reason,
                        }
                    )
                    return
            except Exception:
                logger.debug("Policy check failed", exc_info=True)

        # Context projection
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

        # Memory recall
        if self._memory:
            try:
                items = await self._memory.recall(user_input, limit=5)
                state.recalled_memories = items
                yield _custom(
                    {
                        "type": "soothe.memory.recalled",
                        "count": len(items),
                        "query": user_input[:100],
                    }
                )
            except Exception:
                logger.debug("Memory recall failed", exc_info=True)

        # Plan creation
        if self._planner and self._config.planner_routing != "none":
            try:
                capabilities = [name for name, cfg in self._config.subagents.items() if cfg.enabled]
                context = PlanContext(
                    recent_messages=[user_input],
                    available_capabilities=capabilities,
                    completed_steps=[],
                )
                plan = await self._planner.create_plan(user_input, context)
                state.plan = plan
                self._current_plan = plan
                yield _custom(
                    {
                        "type": "soothe.plan.created",
                        "goal": plan.goal,
                        "steps": [{"id": s.id, "description": s.description, "status": s.status} for s in plan.steps],
                    }
                )
            except Exception:
                logger.debug("Plan creation failed", exc_info=True)

    async def _post_stream(
        self,
        user_input: str,
        state: RunnerState,
    ) -> AsyncGenerator[StreamChunk, None]:
        """Run protocol post-processing after the LangGraph stream."""
        response_text = "".join(state.full_response)

        # Context ingestion
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

        # Context persistence
        if self._context and hasattr(self._context, "persist"):
            try:
                await self._context.persist(state.thread_id)
            except Exception:
                logger.debug("Context persistence failed", exc_info=True)

        # Memory storage for significant responses
        if self._memory and response_text and len(response_text) > 50:
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

        # Plan reflection
        if self._planner and state.plan and response_text:
            try:
                step_results = [
                    StepResult(step_id=s.id, output=s.result or "", success=s.status == "completed")
                    for s in state.plan.steps
                    if s.status in ("completed", "failed")
                ]
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

        # State persistence
        try:
            await self._durability.save_state(
                state.thread_id,
                {
                    "last_query": user_input,
                    "response_preview": response_text[:200],
                },
            )
            yield _custom({"type": "soothe.thread.saved", "thread_id": state.thread_id})
        except Exception:
            logger.debug("State persistence failed", exc_info=True)

        yield _custom({"type": "soothe.session.ended", "thread_id": state.thread_id})

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

    def _accumulate_response(self, data: Any, state: RunnerState) -> None:
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
