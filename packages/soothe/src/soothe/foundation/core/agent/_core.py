"""CoreAgent class definition.

Thin wrapper with typed protocol properties and execution interface.
Pure Layer 1 runtime - NO goal infrastructure (Layer 2/3 responsibility).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from soothe.foundation.loop.engine.ephemeral_execute_stream import ephemeral_execute_stream_enabled
from soothe.utils.text_preview import log_preview

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from deepagents.middleware.subagents import CompiledSubAgent, SubAgent
    from langchain_core.runnables import RunnableConfig
    from langgraph.graph.state import CompiledStateGraph
    from langgraph.pregel.base import BaseCheckpointSaver

    from soothe.config import SootheConfig
    from soothe.protocols.memory import MemoryProtocol
    from soothe.protocols.planner import PlannerProtocol
    from soothe.protocols.policy import PolicyProtocol

logger = logging.getLogger(__name__)


def _normalize_layer1_input(input_arg: str | dict) -> dict:
    """Coerce a bare user string to LangGraph state with one HumanMessage.

    AgentLoop and the runner pass ``{\"messages\": [...]}``; string input is
    supported for convenience and tests.
    """
    if isinstance(input_arg, str):
        from langchain_core.messages import HumanMessage

        return {"messages": [HumanMessage(content=input_arg)]}
    return input_arg


class CoreAgent:
    """Layer 1 CoreAgent runtime interface (RFC-0023).

    Self-contained module wrapping CompiledStateGraph with explicit typed
    protocol properties. Pure execution runtime for tools, subagents, and
    middlewares - NO goal infrastructure (Layer 2/3 responsibility).

    This class wraps LangGraph CompiledStateGraph with Soothe-specific features:
    - LangGraph provides: CompiledStateGraph, built-in middleware stack,
      BackendProtocol, SubAgent/task tool
    - Soothe adds: typed protocol properties, execution hints processing,
      policy enforcement layer, context briefing injection

    Attributes:
        graph: Underlying CompiledStateGraph for advanced LangGraph operations.
        config: SootheConfig used to create this agent.
        memory: MemoryProtocol instance for memory recall/persistence.
        planner: PlannerProtocol instance for planning decisions.
        policy: PolicyProtocol instance for action policy checking.
        subagents: List of configured subagents available for delegation.

    Execution Interface:
        Use `astream(input, config)` for Layer 1 streaming execution.

        Preferred orchestration input is a LangGraph state dict with a
        ``messages`` list of :class:`~langchain_core.messages.BaseMessage`
        instances. A bare string is normalized to a single
        :class:`~langchain_core.messages.HumanMessage` before invoking the
        compiled graph.

        config.configurable may include Layer 2 hints:
            - thread_id: Thread identifier for persistence
            - workspace: Thread-specific workspace path (RFC-103)
            - soothe_step_subagent: when set, first model hop delegates via ``task`` only (IG-386)
            - soothe_step_expected_output: expected result description (advisory text)

    Layer 2 Contract:
        Layer 2 (SootheRunner/AgentLoop) provides:
        - Execution hints via config.configurable (subagent delegation enforcement + advisory text)
        - Classification state (for SystemPromptMiddleware)
        - Thread/workspace management
        - Goal-driven orchestration

        Layer 1 (CoreAgent) provides:
        - astream(input, config) execution
        - Protocol property access (memory, planner, policy)
        - Thread-aware execution via config.configurable

    Example:
        config = SootheConfig.from_file("config.yml")
        agent = create_soothe_agent(config)

        # CoreAgent execution
        async for chunk in agent.astream("query", {"thread_id": "123"}):
            print(chunk)

        # Access protocols via typed properties
        memory = agent.memory

        # Advanced LangGraph operations via graph
        result = agent.graph.invoke({"messages": [...]})
    """

    def __init__(
        self,
        graph: CompiledStateGraph,
        config: SootheConfig,
        memory: MemoryProtocol | None = None,
        planner: PlannerProtocol | None = None,
        policy: PolicyProtocol | None = None,
        subagents: list[SubAgent | CompiledSubAgent] | None = None,
        execute_graph: CompiledStateGraph | None = None,
    ) -> None:
        """Initialize CoreAgent with graph and protocol instances.

        Args:
            graph: CompiledStateGraph from LangGraph runtime.
            config: SootheConfig used for agent creation.
            memory: MemoryProtocol instance (or None if disabled).
            planner: PlannerProtocol instance (or None if disabled).
            policy: PolicyProtocol instance (or None if disabled).
            subagents: List of configured subagents.
            execute_graph: Optional twin graph without checkpointer for execute
                streaming (IG-477). When set and ephemeral execute is enabled,
                ACT-phase streaming uses this graph instead of ``graph``.
        """
        self._graph = graph
        self._execute_graph = execute_graph
        self._config = config
        self._memory = memory
        self._planner = planner
        self._policy = policy
        self._subagents = list(subagents) if subagents else []

    # --- Explicit typed properties ---
    @property
    def graph(self) -> CompiledStateGraph:
        """Underlying CompiledStateGraph for advanced LangGraph operations."""
        return self._graph

    @property
    def execution_graph(self) -> CompiledStateGraph:
        """Graph used for AgentLoop execute streaming (IG-477).

        Returns the checkpointer-free twin when ephemeral execute is enabled;
        otherwise the primary ``graph``.
        """
        if ephemeral_execute_stream_enabled() and self._execute_graph is not None:
            return self._execute_graph
        return self._graph

    @property
    def checkpointer(self) -> BaseCheckpointSaver | None:
        """LangGraph checkpointer for thread state persistence.

        Returns the checkpointer attached to the underlying graph, or None
        if checkpointing is not configured.
        """
        return getattr(self._graph, "checkpointer", None)

    @property
    def config(self) -> SootheConfig:
        """SootheConfig used to create this agent."""
        return self._config

    @property
    def memory(self) -> MemoryProtocol | None:
        """MemoryProtocol instance for memory recall/persistence."""
        return self._memory

    @property
    def planner(self) -> PlannerProtocol | None:
        """PlannerProtocol instance for planning decisions."""
        return self._planner

    @property
    def policy(self) -> PolicyProtocol | None:
        """PolicyProtocol instance for action policy checking."""
        return self._policy

    @property
    def subagents(self) -> list[SubAgent | CompiledSubAgent]:
        """List of configured subagents available for delegation."""
        return self._subagents

    # --- Execution interface ---
    def astream(
        self,
        input_arg: str | dict,
        config: RunnableConfig | None = None,
        *,
        stream_mode: list[str] | None = None,
        subgraphs: bool = False,
        durability: str | None = None,
    ) -> AsyncIterator[Any]:
        """Execute with Layer 1 streaming interface.

        Delegates to underlying CompiledStateGraph.astream(). Use this
        for standard Layer 1 execution from Layer 2 ACT phase or CLI/daemon.

        Args:
            input_arg: User text (coerced to one HumanMessage in graph state) or a
                LangGraph state dict (typically with a ``messages`` key).
            config: RunnableConfig with thread_id and optional Layer 2 hints.
                Layer 2 hints in config.configurable:
                - thread_id: Thread identifier
                - workspace: Thread-specific workspace path
                - soothe_step_subagent: enforce ``task``-only delegation on first hop when set (IG-386)
                - soothe_step_expected_output: expected result (hint text)
            stream_mode: Optional list of stream modes (e.g., ["messages", "updates", "custom"]).
                If None, uses LangGraph defaults.
            subgraphs: Whether to include subgraph events in stream (default: False).
            durability: LangGraph checkpoint durability (``sync``, ``async``, ``exit``).
                Use ``exit`` during high-volume streaming to avoid per-chunk checkpoint
                memory spikes (IG-477).

        Returns:
            AsyncIterator of StreamChunk events from LangGraph execution.

        Example:
            async for chunk in agent.astream(
                "Execute: Find config files",
                {"configurable": {"thread_id": "t-123"}}
            ):
                process(chunk)
        """
        # Log execution start
        thread_id = (
            config.get("configurable", {}).get("thread_id", "unknown") if config else "unknown"
        )
        hints = config.get("configurable", {}) if config else {}

        input_preview = (
            input_arg if isinstance(input_arg, str) else log_preview(str(input_arg), chars=150)
        )
        logger.debug(
            "[Exec] Starting execution (thread=%s): %s",
            thread_id,
            input_preview,
        )

        # Log execution hints if present
        if hints.get("soothe_step_subagent"):
            logger.debug("[Exec] Hint: suggested subagent=%s", hints["soothe_step_subagent"])

        graph_input = _normalize_layer1_input(input_arg)

        if stream_mode:
            return self._graph.astream(
                graph_input,
                config or {},
                stream_mode=stream_mode,
                subgraphs=subgraphs,
                durability=durability,
            )
        return self._graph.astream(
            graph_input,
            config or {},
            subgraphs=subgraphs,
            durability=durability,
        )

    async def aget_state(
        self,
        config: RunnableConfig | None = None,
    ) -> Any:
        """Get current graph state for a thread.

        Args:
            config: RunnableConfig with configurable.thread_id.

        Returns:
            State snapshot from LangGraph aget_state().
        """
        return await self._graph.aget_state(config=config or {})

    async def ainvoke(
        self,
        input_arg: str | dict,
        config: RunnableConfig | None = None,
        *,
        durability: str | None = None,
    ) -> Any:
        """Execute graph to completion without streaming.

        Args:
            input_arg: User text or LangGraph state dict.
            config: RunnableConfig with thread_id and optional hints.
            durability: LangGraph checkpoint durability.

        Returns:
            Final graph state values from ``ainvoke``.
        """
        graph_input = _normalize_layer1_input(input_arg)
        invoke_kwargs: dict[str, Any] = {}
        if durability is not None:
            invoke_kwargs["durability"] = durability
        return await self._graph.ainvoke(graph_input, config or {}, **invoke_kwargs)

    def execution_astream(
        self,
        input_arg: str | dict,
        config: RunnableConfig | None = None,
        *,
        stream_mode: list[str] | None = None,
        subgraphs: bool = False,
        durability: str | None = None,
    ) -> AsyncIterator[Any]:
        """Stream via ``execution_graph`` (IG-477 ephemeral execute path)."""
        graph_input = _normalize_layer1_input(input_arg)
        graph = self.execution_graph
        if stream_mode:
            return graph.astream(
                graph_input,
                config or {},
                stream_mode=stream_mode,
                subgraphs=subgraphs,
                durability=durability,
            )
        return graph.astream(
            graph_input,
            config or {},
            subgraphs=subgraphs,
            durability=durability,
        )

    async def execution_aget_state(
        self,
        config: RunnableConfig | None = None,
    ) -> Any:
        """Read state from ``execution_graph`` after an execute stream."""
        return await self.execution_graph.aget_state(config=config or {})

    async def execution_ainvoke(
        self,
        input_arg: str | dict,
        config: RunnableConfig | None = None,
        *,
        durability: str | None = None,
    ) -> Any:
        """Invoke ``execution_graph`` without streaming."""
        graph_input = _normalize_layer1_input(input_arg)
        invoke_kwargs: dict[str, Any] = {}
        if durability is not None:
            invoke_kwargs["durability"] = durability
        return await self.execution_graph.ainvoke(graph_input, config or {}, **invoke_kwargs)

    @classmethod
    def create(cls, config: SootheConfig | None = None, **kwargs: Any) -> CoreAgent:
        """Factory method - delegates to create_soothe_agent().

        Args:
            config: Soothe configuration. If None, uses defaults.
            **kwargs: Additional arguments passed to create_soothe_agent().

        Returns:
            CoreAgent instance.
        """
        from soothe.foundation.core.agent._builder import create_soothe_agent

        return create_soothe_agent(config, **kwargs)
