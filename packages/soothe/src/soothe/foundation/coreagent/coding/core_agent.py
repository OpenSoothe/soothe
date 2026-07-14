"""CoreAgent class definition.

Thin wrapper with typed protocol properties and execution interface.
Pure Layer 1 runtime - NO goal infrastructure (Layer 2/3 responsibility).
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from soothe.foundation.sloop.engine.executor import ephemeral_execute_stream_enabled
from soothe.utils.text_preview import log_preview

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from langchain_core.runnables import RunnableConfig
    from langgraph.graph.state import CompiledStateGraph
    from langgraph.pregel.base import BaseCheckpointSaver
    from soothe_deepagents.middleware.subagents import CompiledSubAgent, SubAgent

    from soothe.config import SootheConfig
    from soothe.protocols.core_agent import CoreAgentCapabilities
    from soothe.protocols.memory import MemoryProtocol
    from soothe.protocols.planner import PlannerProtocol
    from soothe.protocols.policy import PolicyProtocol

logger = logging.getLogger(__name__)


def _persisted_checkpointer(graph: Any) -> Any:
    """Return the graph checkpointer when it can persist thread state."""
    from langgraph.checkpoint.base import BaseCheckpointSaver

    cp = getattr(graph, "checkpointer", None)
    return cp if isinstance(cp, BaseCheckpointSaver) else None


def _state_retrieval_config(config: RunnableConfig | None) -> dict[str, Any]:
    """Build RunnableConfig safe for ``aget_state`` after ephemeral execute streams.

    Ephemeral twin graphs (IG-477) can leave ``__pregel_checkpointer: None`` on the
    shared config dict. LangGraph then refuses to read state even when the primary
    graph has a checkpointer attached.
    """
    from langgraph._internal._constants import CONFIG_KEY_CHECKPOINTER

    if not config:
        return {}
    out: dict[str, Any] = dict(config)
    conf = dict(out.get("configurable") or {})
    if conf.get(CONFIG_KEY_CHECKPOINTER) is None:
        conf.pop(CONFIG_KEY_CHECKPOINTER, None)
    if conf:
        out["configurable"] = conf
    elif "configurable" in out:
        del out["configurable"]
    return out


def _normalize_layer1_input(input_arg: str | dict) -> dict:
    """Coerce a bare user string to LangGraph state with one HumanMessage.

    StrangeLoop and the runner pass ``{"messages": [...]}``; string input is
    supported for convenience and tests.
    """
    if isinstance(input_arg, str):
        from langchain_core.messages import HumanMessage

        return {"messages": [HumanMessage(content=input_arg)]}
    return input_arg


class CodingCoreAgent:
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
        Layer 2 (SootheRunner/StrangeLoop) provides:
        - Execution hints via config.configurable (subagent delegation enforcement + advisory text)
        - Classification state (for SystemPromptMiddleware)
        - Thread/workspace management
        - Goal-driven orchestration

        Layer 1 (CoreAgent) provides:
        - astream(input, config) execution
        - Protocol property access (memory, planner, policy)
        - Thread-aware execution via config.configurable
    """

    def __init__(
        self,
        graph: CompiledStateGraph,
        config: SootheConfig,
        memory: MemoryProtocol | None = None,
        planner: PlannerProtocol | None = None,
        policy: PolicyProtocol | None = None,
        subagents: list[SubAgent | CompiledSubAgent] | None = None,
        capabilities: CoreAgentCapabilities | None = None,
        execute_graph: CompiledStateGraph | None = None,
        execute_graph_compiler: Callable[[], CompiledStateGraph] | None = None,
    ) -> None:
        self._graph = graph
        self._execute_graph = execute_graph
        self._execute_graph_compiler = execute_graph_compiler
        self._config = config
        self._memory = memory
        self._planner = planner
        self._policy = policy
        self._subagents = list(subagents) if subagents else []
        if capabilities is None:
            from soothe.protocols.core_agent import CoreAgentCapabilities

            capabilities = CoreAgentCapabilities(
                subagents=tuple(str(getattr(subagent, "name", "")) for subagent in self._subagents),
                features=("langgraph", "checkpointer", "execution_graph"),
            )
        self._capabilities = capabilities

    @property
    def graph(self) -> CompiledStateGraph:
        return self._graph

    @property
    def execution_graph(self) -> CompiledStateGraph:
        if ephemeral_execute_stream_enabled():
            if self._execute_graph is None and self._execute_graph_compiler is not None:
                execute_start = time.perf_counter()
                self._execute_graph = self._execute_graph_compiler()
                execute_ms = (time.perf_counter() - execute_start) * 1000
                logger.info(
                    "[Init] Ephemeral execute graph created (%.1fms, IG-477 lazy)",
                    execute_ms,
                )
            if self._execute_graph is not None:
                return self._execute_graph
        return self._graph

    @property
    def checkpointer(self) -> BaseCheckpointSaver | None:
        return _persisted_checkpointer(self._graph)

    @property
    def can_read_graph_state(self) -> bool:
        return self.checkpointer is not None

    @property
    def config(self) -> SootheConfig:
        return self._config

    @property
    def memory(self) -> MemoryProtocol | None:
        return self._memory

    @property
    def planner(self) -> PlannerProtocol | None:
        return self._planner

    @property
    def policy(self) -> PolicyProtocol | None:
        return self._policy

    @property
    def subagents(self) -> list[SubAgent | CompiledSubAgent]:
        return self._subagents

    def list_capabilities(self) -> CoreAgentCapabilities:
        return self._capabilities

    def astream(
        self,
        input_arg: str | dict,
        config: RunnableConfig | None = None,
        *,
        stream_mode: list[str] | None = None,
        subgraphs: bool = False,
        durability: str | None = None,
    ) -> AsyncIterator[Any]:
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
        if not self.can_read_graph_state:
            return None
        try:
            return await self._graph.aget_state(config=_state_retrieval_config(config))
        except ValueError as exc:
            if "No checkpointer set" in str(exc):
                logger.debug("[Exec] Cannot get state: no checkpointer configured")
                return None
            raise

    async def ainvoke(
        self,
        input_arg: str | dict,
        config: RunnableConfig | None = None,
        *,
        durability: str | None = None,
    ) -> Any:
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

    def execute_stream(
        self,
        input_arg: str | dict,
        config: RunnableConfig | None = None,
        *,
        stream_mode: list[str] | None = None,
        subgraphs: bool = False,
    ) -> AsyncIterator[Any]:
        return self.execution_astream(
            input_arg,
            config=config,
            stream_mode=stream_mode,
            subgraphs=subgraphs,
            durability="exit",
        )

    async def execution_aget_state(
        self,
        config: RunnableConfig | None = None,
    ) -> Any:
        if not self.can_read_graph_state:
            return None
        try:
            return await self._graph.aget_state(config=_state_retrieval_config(config))
        except ValueError as exc:
            if "No checkpointer set" in str(exc):
                logger.debug("[Exec] Cannot get state: no checkpointer configured")
                return None
            raise

    async def read_runtime_state(
        self,
        config: RunnableConfig | None = None,
        *,
        execution_scope: bool = False,
    ) -> Any:
        if execution_scope:
            return await self.execution_aget_state(config=config)
        return await self.aget_state(config=config)

    async def execution_ainvoke(
        self,
        input_arg: str | dict,
        config: RunnableConfig | None = None,
        *,
        durability: str | None = None,
    ) -> Any:
        graph_input = _normalize_layer1_input(input_arg)
        invoke_kwargs: dict[str, Any] = {}
        if durability is not None:
            invoke_kwargs["durability"] = durability
        return await self.execution_graph.ainvoke(graph_input, config or {}, **invoke_kwargs)

    @classmethod
    def create(cls, config: SootheConfig | None = None, **kwargs: Any) -> CodingCoreAgent:
        from soothe.foundation.coreagent.coding.builder import create_soothe_agent

        return create_soothe_agent(config, **kwargs)


CoreAgent = CodingCoreAgent
