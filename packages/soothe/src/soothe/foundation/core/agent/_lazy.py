"""Lazy CoreAgent wrapper (IG-506).

Defers ``create_soothe_agent`` graph compilation until the first Layer-1
execution access (execute stream, checkpointer, or explicit materialize).
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import TYPE_CHECKING, Any

from soothe.foundation.core.agent._core import CoreAgent

if TYPE_CHECKING:
    from deepagents.middleware.subagents import CompiledSubAgent, SubAgent
    from langchain_core.runnables import RunnableConfig
    from langgraph.graph.state import CompiledStateGraph
    from langgraph.pregel.base import BaseCheckpointSaver

    from soothe.config import SootheConfig
    from soothe.protocols.memory import MemoryProtocol
    from soothe.protocols.planner import PlannerProtocol
    from soothe.protocols.policy import PolicyProtocol

logger = logging.getLogger(__name__)

MaterializeHook = Callable[[CoreAgent], Awaitable[None] | None]


class LazyCoreAgent:
    """Proxy that compiles the real CoreAgent on first Layer-1 use.

    StrangeLoop planning and loop-graph orchestration can proceed without paying
    the ``create_deep_agent`` compile cost up front.
    """

    def __init__(
        self,
        factory: Callable[[], CoreAgent],
        *,
        memory: MemoryProtocol | None = None,
        planner: PlannerProtocol | None = None,
        policy: PolicyProtocol | None = None,
        config: SootheConfig | None = None,
        materialize_hook: MaterializeHook | None = None,
    ) -> None:
        self._factory = factory
        self._delegate: CoreAgent | None = None
        self._memory = memory
        self._planner = planner
        self._policy = policy
        self._config = config
        self._materialize_hook = materialize_hook

    @property
    def is_materialized(self) -> bool:
        """Return True once the underlying CoreAgent has been compiled."""
        return self._delegate is not None

    def materialize(self) -> CoreAgent:
        """Compile and cache the underlying CoreAgent."""
        if self._delegate is None:
            self._delegate = self._factory()
            logger.info("[Init] LazyCoreAgent materialized")
        return self._delegate

    async def amaterialize(self) -> CoreAgent:
        """Materialize and run optional async hook (e.g. checkpointer attach)."""
        agent = self.materialize()
        if self._materialize_hook is not None:
            result = self._materialize_hook(agent)
            if result is not None:
                await result
        return agent

    @property
    def graph(self) -> CompiledStateGraph:
        return self.materialize().graph

    @property
    def execution_graph(self) -> CompiledStateGraph:
        return self.materialize().execution_graph

    @property
    def checkpointer(self) -> BaseCheckpointSaver | None:
        return self.materialize().checkpointer

    @property
    def can_read_graph_state(self) -> bool:
        return self.materialize().can_read_graph_state

    @property
    def config(self) -> SootheConfig:
        if self._config is not None:
            return self._config
        return self.materialize().config

    @property
    def memory(self) -> MemoryProtocol | None:
        if self._memory is not None:
            return self._memory
        return self.materialize().memory

    @property
    def planner(self) -> PlannerProtocol | None:
        if self._planner is not None:
            return self._planner
        return self.materialize().planner

    @property
    def policy(self) -> PolicyProtocol | None:
        if self._policy is not None:
            return self._policy
        return self.materialize().policy

    @property
    def subagents(self) -> list[SubAgent | CompiledSubAgent]:
        return self.materialize().subagents

    def astream(
        self,
        input_arg: str | dict,
        config: RunnableConfig | None = None,
        *,
        stream_mode: list[str] | None = None,
        subgraphs: bool = False,
        durability: str | None = None,
    ) -> AsyncIterator[Any]:
        return self.materialize().astream(
            input_arg,
            config,
            stream_mode=stream_mode,
            subgraphs=subgraphs,
            durability=durability,
        )

    async def aget_state(self, config: RunnableConfig | None = None) -> Any:
        return await self.materialize().aget_state(config=config)

    async def ainvoke(
        self,
        input_arg: str | dict,
        config: RunnableConfig | None = None,
        *,
        durability: str | None = None,
    ) -> Any:
        return await self.materialize().ainvoke(input_arg, config, durability=durability)

    def execution_astream(
        self,
        input_arg: str | dict,
        config: RunnableConfig | None = None,
        *,
        stream_mode: list[str] | None = None,
        subgraphs: bool = False,
        durability: str | None = None,
    ) -> AsyncIterator[Any]:
        return self.materialize().execution_astream(
            input_arg,
            config,
            stream_mode=stream_mode,
            subgraphs=subgraphs,
            durability=durability,
        )

    async def execution_aget_state(self, config: RunnableConfig | None = None) -> Any:
        agent = await self.amaterialize()
        return await agent.execution_aget_state(config=config)

    async def execution_ainvoke(
        self,
        input_arg: str | dict,
        config: RunnableConfig | None = None,
        *,
        durability: str | None = None,
    ) -> Any:
        return await self.materialize().execution_ainvoke(input_arg, config, durability=durability)
