"""CoreAgentProtocol - Layer 1 runtime interface.

CoreAgent is the foundational execution runtime, unaware of Loop or Autopilot
concepts. It provides pure tool/subagent execution with middleware processing.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    from langchain_core.runnables import RunnableConfig
    from langgraph.graph.state import CompiledStateGraph
    from langgraph.pregel.base import BaseCheckpointSaver

    from soothe.config import SootheConfig


@runtime_checkable
class CoreAgentProtocol(Protocol):
    """Layer 1 runtime interface - unaware of Loop or Autopilot concepts.

    CoreAgent provides pure execution runtime for:
    - Tool invocation
    - Subagent delegation (via deepagents task tool)
    - Middleware processing
    - Streaming execution

    This protocol enables alternative CoreAgent implementations while
    keeping the execution contract stable for Loop/Autopilot layers.

    Implementation requirements:
    - Must support config.configurable hints:
      - thread_id: Thread identifier for persistence
      - workspace: Thread-specific workspace path
      - soothe_step_subagent: Advisory subagent hint
      - soothe_step_expected_output: Advisory expected result
    - Must apply Soothe middleware stack (policy, prompts, hints, workspace)
    - Must return streaming results compatible with LangGraph stream modes
    """

    @property
    def graph(self) -> CompiledStateGraph:
        """Underlying LangGraph for advanced operations.

        Note: This property is implementation-specific. Alternative
        implementations may not use LangGraph and should raise
        NotImplementedError or return a compatible adapter.
        """
        ...

    @property
    def checkpointer(self) -> BaseCheckpointSaver | None:
        """LangGraph checkpointer for thread state persistence.

        Returns None if checkpointing is disabled.
        """
        ...

    async def aget_state(
        self,
        config: RunnableConfig | None = None,
    ) -> Any:
        """Get current graph state for a thread.

        Args:
            config: RunnableConfig with configurable.thread_id.

        Returns:
            State snapshot or None if unavailable (non-LangGraph implementations).

        Note: Alternative implementations may return None if they don't
        support state snapshots.
        """
        ...

    async def astream(
        self,
        input_arg: str | dict,
        config: RunnableConfig | None = None,
        *,
        stream_mode: list[str] | None = None,
        subgraphs: bool = False,
    ) -> AsyncIterator[Any]:
        """Execute with streaming interface.

        Args:
            input_arg: User text (normalized to HumanMessage) or LangGraph
                state dict with 'messages' key.
            config: RunnableConfig with:
                - configurable.thread_id: Thread identifier
                - configurable.workspace: Thread workspace path
                - configurable.soothe_step_subagent: Subagent hint (optional)
                - configurable.soothe_step_expected_output: Result hint (optional)
            stream_mode: Stream modes - ["messages", "updates", "custom"]
            subgraphs: Include subgraph events in stream

        Returns:
            AsyncIterator yielding stream chunks. Chunk format depends
            on stream_mode:
            - "messages": (message_metadata, message_chunk)
            - "updates": (node_name, update_dict)
            - "custom": custom event dicts
        """
        ...

    @classmethod
    def create(cls, config: SootheConfig, **kwargs: Any) -> CoreAgentProtocol:
        """Factory method for creating CoreAgent instances.

        Args:
            config: SootheConfig with provider/model settings
            **kwargs: Implementation-specific arguments

        Returns:
            CoreAgentProtocol instance ready for execution
        """
        ...
