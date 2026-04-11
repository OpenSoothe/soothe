"""CoreAgent class definition.

Thin wrapper with typed protocol properties and execution interface.
Pure Layer 1 runtime - NO goal infrastructure (Layer 2/3 responsibility).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from soothe.utils.text_preview import preview_first

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from deepagents.middleware.subagents import CompiledSubAgent, SubAgent
    from langchain_core.runnables import RunnableConfig
    from langgraph.graph.state import CompiledStateGraph

    from soothe.config import SootheConfig
    from soothe.protocols.memory import MemoryProtocol
    from soothe.protocols.planner import PlannerProtocol
    from soothe.protocols.policy import PolicyProtocol

logger = logging.getLogger(__name__)


class CoreAgent:
    """Layer 1 CoreAgent runtime interface (RFC-0023).

    Self-contained module wrapping CompiledStateGraph with explicit typed
    protocol properties. Pure execution runtime for tools, subagents, and
    middlewares - NO goal infrastructure (Layer 2/3 responsibility).

    This class defines the clear boundary between Soothe and deepagents:
    - deepagents provides: create_deep_agent(), CompiledStateGraph, built-in
      middleware stack, BackendProtocol, SubAgent/task tool
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

        config.configurable may include Layer 2 hints (advisory):
            - thread_id: Thread identifier for persistence
            - workspace: Thread-specific workspace path (RFC-103)
            - soothe_step_tools: suggested tools for this step
            - soothe_step_subagent: suggested subagent for this step
            - soothe_step_expected_output: expected result description

    Layer 2 Contract:
        Layer 2 (SootheRunner/AgentLoop) provides:
        - Execution hints via config.configurable (advisory suggestions)
        - Classification state (for SystemPromptOptimization)
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
    ) -> None:
        """Initialize CoreAgent with graph and protocol instances.

        Args:
            graph: CompiledStateGraph from deepagents create_deep_agent().
            config: SootheConfig used for agent creation.
            memory: MemoryProtocol instance (or None if disabled).
            planner: PlannerProtocol instance (or None if disabled).
            policy: PolicyProtocol instance (or None if disabled).
            subagents: List of configured subagents.
        """
        self._graph = graph
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
    ) -> AsyncIterator[Any]:
        """Execute with Layer 1 streaming interface.

        Delegates to underlying CompiledStateGraph.astream(). Use this
        for standard Layer 1 execution from Layer 2 ACT phase or CLI/daemon.

        Args:
            input_arg: User query or execution instruction (str or dict with
                "messages" key for LangGraph format).
            config: RunnableConfig with thread_id and optional Layer 2 hints.
                Layer 2 hints in config.configurable (advisory):
                - thread_id: Thread identifier
                - workspace: Thread-specific workspace path
                - soothe_step_tools: suggested tools for this step
                - soothe_step_subagent: suggested subagent
                - soothe_step_expected_output: expected result
            stream_mode: Optional list of stream modes (e.g., ["messages", "updates", "custom"]).
                If None, uses LangGraph defaults.
            subgraphs: Whether to include subgraph events in stream (default: False).

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
        thread_id = config.get("configurable", {}).get("thread_id", "unknown") if config else "unknown"
        hints = config.get("configurable", {}) if config else {}

        input_preview = input_arg if isinstance(input_arg, str) else preview_first(str(input_arg), 80)
        logger.debug(
            "[Exec] Starting execution (thread=%s): %s",
            thread_id,
            preview_first(input_preview, 80),
        )

        # Log execution hints if present
        if hints.get("soothe_step_tools"):
            logger.debug("[Exec] Hint: suggested tools=%s", hints["soothe_step_tools"])
        if hints.get("soothe_step_subagent"):
            logger.debug("[Exec] Hint: suggested subagent=%s", hints["soothe_step_subagent"])

        if stream_mode:
            return self._graph.astream(input_arg, config or {}, stream_mode=stream_mode, subgraphs=subgraphs)
        return self._graph.astream(input_arg, config or {}, subgraphs=subgraphs)

    @classmethod
    def create(cls, config: SootheConfig | None = None, **kwargs: Any) -> CoreAgent:
        """Factory method - delegates to create_soothe_agent().

        Args:
            config: Soothe configuration. If None, uses defaults.
            **kwargs: Additional arguments passed to create_soothe_agent().

        Returns:
            CoreAgent instance.
        """
        from soothe.core.agent._builder import create_soothe_agent

        return create_soothe_agent(config, **kwargs)
