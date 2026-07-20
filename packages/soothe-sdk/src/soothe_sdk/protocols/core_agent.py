"""CoreAgentProtocol — Coding CoreAgent runtime interface.

CoreAgent is the foundational execution runtime, unaware of host orchestration.
It provides pure tool/subagent execution with middleware processing.

LangGraph / config types are typed as ``Any`` so this contract stays in
``soothe-sdk`` without depending on ``soothe-nano`` or ``langgraph``.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


@dataclass(slots=True)
class CoreAgentCapabilities:
    """Runtime capability inventory for planning and orchestration."""

    tools: tuple[str, ...] = ()
    subagents: tuple[str, ...] = ()
    features: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class CoreAgentProtocol(Protocol):
    """Coding CoreAgent runtime interface — unaware of host orchestration layers.

    CoreAgent provides pure execution runtime for:
    - Tool invocation
    - Subagent delegation (via soothe_deepagents task tool)
    - Middleware processing
    - Streaming execution

    This protocol enables alternative CoreAgent implementations while
    keeping the execution contract stable for host orchestration.

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
    def graph(self) -> Any:
        """Underlying graph for advanced operations (typically a LangGraph).

        Note: This property is implementation-specific. Alternative
        implementations may not use LangGraph and should raise
        NotImplementedError or return a compatible adapter.
        """
        ...

    @property
    def checkpointer(self) -> Any | None:
        """Checkpointer for thread state persistence.

        Returns None if checkpointing is disabled.
        """
        ...

    async def aget_state(
        self,
        config: Any | None = None,
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

    async def execution_aget_state(
        self,
        config: Any | None = None,
    ) -> Any:
        """Get execution-graph state when execute graph differs from primary graph.

        Implementations without a separate execution graph can return the same
        state as ``aget_state``.
        """
        ...

    async def read_runtime_state(
        self,
        config: Any | None = None,
        *,
        execution_scope: bool = False,
    ) -> Any:
        """Read runtime state from primary or execute stream scope."""
        ...

    async def astream(
        self,
        input_arg: str | dict,
        config: Any | None = None,
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

    def execution_astream(
        self,
        input_arg: str | dict,
        config: Any | None = None,
        *,
        stream_mode: list[str] | None = None,
        subgraphs: bool = False,
    ) -> AsyncIterator[Any]:
        """Execute via runtime's execute-optimized stream path.

        Implementations without a dedicated execute stream can delegate to
        ``astream``.
        """
        ...

    def execute_stream(
        self,
        input_arg: str | dict,
        config: Any | None = None,
        *,
        stream_mode: list[str] | None = None,
        subgraphs: bool = False,
    ) -> AsyncIterator[Any]:
        """Canonical execute stream abstraction used by orchestrators."""
        ...

    @property
    def can_read_graph_state(self) -> bool:
        """Whether runtime state retrieval is supported for checkpoint thread state."""
        ...

    def list_capabilities(self) -> CoreAgentCapabilities:
        """Return tools/subagents/features visible to host planning."""
        ...

    @classmethod
    def create(cls, config: Any, **kwargs: Any) -> CoreAgentProtocol:
        """Factory method for creating CoreAgent instances.

        Args:
            config: Host config with provider/model settings (e.g. SootheConfig)
            **kwargs: Implementation-specific arguments

        Returns:
            CoreAgentProtocol instance ready for execution
        """
        ...
