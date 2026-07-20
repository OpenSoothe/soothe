"""Coding CoreAgent class definition.

Thin wrapper with typed protocol properties and execution interface.
Pure CoreAgent runtime — no StrangeLoop / Autopilot infrastructure.
"""

from __future__ import annotations

import logging
import os
import time
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from soothe_sdk.protocols.core_agent import CoreAgentCapabilities

from soothe_nano.utils.text_preview import log_preview

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from langchain_core.runnables import RunnableConfig
    from langgraph.graph.state import CompiledStateGraph
    from langgraph.pregel.base import BaseCheckpointSaver
    from soothe_deepagents.middleware.subagents import CompiledSubAgent, SubAgent

logger = logging.getLogger(__name__)


def ephemeral_execute_stream_enabled() -> bool:
    """Whether execute uses the checkpointer-free twin graph (default: on).

    LangGraph graphs compiled with a checkpointer load checkpoint channel history on
    each ``astream`` tick, causing unbounded RSS during execute. CoreAgent therefore
    builds a twin graph with ``checkpointer=None`` for execute-only streaming while
    the main graph keeps durable checkpointer state for other sessions.

    Set ``SOOTHE_EPHEMERAL_EXECUTE_STREAM=0`` only for emergency rollback.
    """
    return os.environ.get("SOOTHE_EPHEMERAL_EXECUTE_STREAM", "1").lower() not in (
        "0",
        "false",
        "no",
    )


def _persisted_checkpointer(graph: Any) -> Any:
    """Return the graph checkpointer when it can persist thread state."""
    from langgraph.checkpoint.base import BaseCheckpointSaver

    cp = getattr(graph, "checkpointer", None)
    return cp if isinstance(cp, BaseCheckpointSaver) else None


def _state_retrieval_config(config: RunnableConfig | None) -> dict[str, Any]:
    """Build RunnableConfig safe for ``aget_state`` after ephemeral execute streams.

    Ephemeral twin graphs can leave ``__pregel_checkpointer: None`` on the
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

    Hosts pass ``{\"messages\": [...]}``; string input is supported for convenience
    and tests.
    """
    if isinstance(input_arg, str):
        from langchain_core.messages import HumanMessage

        return {"messages": [HumanMessage(content=input_arg)]}
    return input_arg


class CodingCoreAgent:
    """Coding CoreAgent runtime interface.

    Self-contained module wrapping CompiledStateGraph with explicit typed
    protocol properties. Pure execution runtime for tools, subagents, and
    middlewares — no goal infrastructure (host orchestration layers).

    Attributes:
        graph: Underlying CompiledStateGraph for advanced LangGraph operations.
        config: Host configuration object used to create this agent.
        memory: Optional memory protocol instance.
        planner: Optional planner protocol instance.
        policy: Optional policy protocol instance.
        subagents: List of configured subagents available for delegation.
    """

    def __init__(
        self,
        graph: CompiledStateGraph,
        config: Any,
        memory: Any | None = None,
        planner: Any | None = None,
        policy: Any | None = None,
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
                    "[Init] Ephemeral execute graph created (%.1fms, lazy)",
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
    def config(self) -> Any:
        return self._config

    @property
    def memory(self) -> Any | None:
        return self._memory

    @property
    def planner(self) -> Any | None:
        return self._planner

    @property
    def policy(self) -> Any | None:
        return self._policy

    @property
    def subagents(self) -> list[SubAgent | CompiledSubAgent]:
        """Subagents bound on the CoreAgent ``task`` catalog."""
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

        input_preview = (
            input_arg if isinstance(input_arg, str) else log_preview(str(input_arg), chars=150)
        )
        logger.debug(
            "[Exec] Starting execution (thread=%s): %s",
            thread_id,
            input_preview,
        )

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
