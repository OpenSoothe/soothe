"""ClaudeCoreAgent - Alternative CoreAgent implementation using claude-agent-sdk.

This module provides a CoreAgent implementation that uses the Claude Code CLI
via claude-agent-sdk instead of LangGraph. It implements CoreAgentProtocol
to allow switching between LangGraph-based and Claude-based execution.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Generator
from contextlib import aclosing
from pathlib import Path
from typing import TYPE_CHECKING, Any

from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage

from soothe.subagents.claude.session_bridge import (
    record_claude_session,
    resolve_resume_session_id,
)
from soothe.utils.path import expand_path

if TYPE_CHECKING:
    from langchain_core.runnables import RunnableConfig
    from langgraph.graph.state import CompiledStateGraph
    from langgraph.pregel.base import BaseCheckpointSaver

    from soothe.config import SootheConfig
    from soothe.protocols.memory import MemoryProtocol
    from soothe.protocols.planner import PlannerProtocol
    from soothe.protocols.policy import PolicyProtocol

logger = logging.getLogger(__name__)


class ClaudeCoreAgent:
    """Alternative CoreAgent implementation using claude-agent-sdk.

    Implements CoreAgentProtocol without LangGraph. Uses Claude Code CLI
    via claude-agent-sdk for full tool capabilities (file ops, bash,
    web search, MCP, subagent spawning).

    This implementation:
    - Does not use LangGraph internally
    - Manages conversation state in-memory per thread
    - Converts claude-agent-sdk events to LangGraph-compatible stream format
    - Supports session resume for thread continuity
    - Provides graph property that raises NotImplementedError (not applicable)

    Attributes:
        config: SootheConfig used to create this agent.
        memory: MemoryProtocol instance for memory recall/persistence.
        planner: PlannerProtocol instance for planning decisions.
        policy: PolicyProtocol instance for action policy checking.
        subagents: Empty list (Claude Code handles subagent spawning internally).
    """

    def __init__(
        self,
        config: SootheConfig,
        model: str | None = None,
        system_prompt: str | None = None,
        permission_mode: str = "bypassPermissions",
        max_turns: int = 25,
        cwd: str | None = None,
        memory: MemoryProtocol | None = None,
        planner: PlannerProtocol | None = None,
        policy: PolicyProtocol | None = None,
    ) -> None:
        """Initialize ClaudeCoreAgent.

        Args:
            config: SootheConfig with provider/model settings.
            model: Claude model name (e.g., 'sonnet', 'opus'). None = SDK default.
            system_prompt: Custom system prompt for Claude.
            permission_mode: Claude Code permission mode (default: bypassPermissions).
            max_turns: Maximum Claude Code turns per execution (default: 25).
            cwd: Working directory for Claude Code. None = current directory.
            memory: MemoryProtocol instance (or None if disabled).
            planner: PlannerProtocol instance (or None if disabled).
            policy: PolicyProtocol instance (or None if disabled).
        """
        self._config = config
        self._model = model
        self._system_prompt = system_prompt
        self._permission_mode = permission_mode
        self._max_turns = max_turns
        self._cwd = cwd or str(Path.cwd())
        self._memory = memory
        self._planner = planner
        self._policy = policy
        self._subagents: list[Any] = []

    @property
    def graph(self) -> CompiledStateGraph:
        """Not applicable - ClaudeCoreAgent uses claude-agent-sdk, not LangGraph.

        Raises:
            NotImplementedError: Always, as this implementation does not use LangGraph.
        """
        raise NotImplementedError(
            "ClaudeCoreAgent uses claude-agent-sdk, not LangGraph. Use astream() for execution."
        )

    @property
    def checkpointer(self) -> BaseCheckpointSaver | None:
        """Not applicable - ClaudeCoreAgent manages state via claude-agent-sdk sessions.

        Returns None since there's no LangGraph checkpointer. Claude Code CLI
        handles session persistence internally via --resume session IDs.
        """
        return None

    async def aget_state(
        self,
        config: RunnableConfig | None = None,
    ) -> Any:
        """Not applicable - ClaudeCoreAgent doesn't use LangGraph state.

        Returns None since there's no LangGraph state to retrieve. Claude Code
        CLI manages conversation state internally via session IDs.

        Args:
            config: RunnableConfig (ignored, not applicable).

        Returns:
            None - no LangGraph state available.
        """
        return None

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
    def subagents(self) -> list[Any]:
        """Empty list - Claude Code handles subagent spawning internally."""
        return self._subagents

    async def astream(
        self,
        input_arg: str | dict,
        config: RunnableConfig | None = None,
        *,
        stream_mode: list[str] | None = None,
        subgraphs: bool = False,
    ) -> AsyncIterator[Any]:
        """Execute using claude-agent-sdk query() with streaming.

        Args:
            input_arg: User text (str) or LangGraph state dict with 'messages' key.
            config: RunnableConfig with thread_id and optional hints.
            stream_mode: Stream modes - ["messages", "updates", "custom"].
            subgraphs: Ignored (not applicable for Claude Code).

        Yields:
            Stream chunks in LangGraph-compatible format:
            - "messages": (metadata, AIMessageChunk)
            - "updates": (node_name, update_dict)
            - "custom": custom event dicts (tool use events)

        Example:
            async for chunk in agent.astream(
                "Execute: Find config files",
                {"configurable": {"thread_id": "t-123"}}
            ):
                process(chunk)
        """
        from claude_agent_sdk import (
            AssistantMessage,
            ClaudeAgentOptions,
            ResultMessage,
            TextBlock,
            ToolUseBlock,
            query,
        )

        thread_id = self._resolve_thread_id(config)
        user_text = self._extract_user_text(input_arg)

        logger.debug(
            "[ClaudeCoreAgent] Starting execution (thread=%s): %s",
            thread_id or "unknown",
            user_text[:100] if user_text else "<empty>",
        )

        # Build Claude options
        options = ClaudeAgentOptions(
            permission_mode=self._permission_mode,
            max_turns=self._max_turns,
        )
        if self._model:
            options.model = self._model
        if self._system_prompt:
            options.system_prompt = self._system_prompt
        options.cwd = self._resolve_cwd(config)

        # Session resume support
        resume_sid = await resolve_resume_session_id(
            thread_id=thread_id,
            cwd=options.cwd,
            claude_sessions_from_config={},
        )
        if resume_sid:
            options.resume = resume_sid
            logger.debug("[ClaudeCoreAgent] Resuming session: %s", resume_sid)

        logger.debug(
            "[ClaudeCoreAgent] Options: model=%s, cwd=%s, permission_mode=%s, max_turns=%d",
            self._model or "<default>",
            options.cwd,
            self._permission_mode,
            self._max_turns,
        )

        # Stream Claude Code execution
        collected_text: list[str] = []
        cost_usd: float = 0.0
        session_id: str | None = None

        try:
            async with aclosing(query(prompt=user_text, options=options)) as stream:
                async for message in stream:
                    if isinstance(message, AssistantMessage):
                        for block in message.content:
                            if isinstance(block, TextBlock):
                                collected_text.append(block.text)
                                for chunk in self._emit_text_chunks(
                                    block.text, stream_mode, thread_id
                                ):
                                    yield chunk
                            elif isinstance(block, ToolUseBlock):
                                for chunk in self._emit_tool_use_chunks(
                                    block, stream_mode, thread_id
                                ):
                                    yield chunk
                    elif isinstance(message, ResultMessage):
                        cost_usd = message.total_cost_usd or 0.0
                        session_id = getattr(message, "session_id", None)
                        duration_ms = int(getattr(message, "duration_ms", 0) or 0)
                        logger.debug(
                            "[ClaudeCoreAgent] Result: cost_usd=%.4f, duration_ms=%d, session_id=%s",
                            cost_usd,
                            duration_ms,
                            session_id or "<none>",
                        )
        except Exception:
            logger.exception("[ClaudeCoreAgent] Execution failed")
            collected_text.append("Claude agent encountered an error.")

        # Record session for resume
        if session_id:
            await record_claude_session(
                thread_id=thread_id,
                cwd=options.cwd,
                session_id=session_id,
                durability=None,
            )

        # Emit final update
        if stream_mode and "updates" in stream_mode:
            result = "\n".join(collected_text) or "Claude task completed."
            if cost_usd > 0:
                result += f"\n\n[Cost: ${cost_usd:.4f}]"
            yield ("agent", {"messages": [AIMessage(content=result)]})

        logger.debug(
            "[ClaudeCoreAgent] Execution complete: result_length=%d, total_cost=%.4f",
            len(collected_text),
            cost_usd,
        )

    @classmethod
    def create(cls, config: SootheConfig, **kwargs: Any) -> ClaudeCoreAgent:
        """Factory method for creating ClaudeCoreAgent instances.

        Args:
            config: SootheConfig with provider/model settings.
            **kwargs: Implementation-specific arguments:
                - model: Claude model name
                - system_prompt: Custom system prompt
                - permission_mode: Claude Code permission mode
                - max_turns: Maximum turns per execution
                - cwd: Working directory
                - memory: MemoryProtocol instance
                - planner: PlannerProtocol instance
                - policy: PolicyProtocol instance

        Returns:
            ClaudeCoreAgent instance ready for execution.
        """
        return cls(
            config=config,
            model=kwargs.get("model"),
            system_prompt=kwargs.get("system_prompt"),
            permission_mode=kwargs.get("permission_mode", "bypassPermissions"),
            max_turns=kwargs.get("max_turns", 25),
            cwd=kwargs.get("cwd"),
            memory=kwargs.get("memory"),
            planner=kwargs.get("planner"),
            policy=kwargs.get("policy"),
        )

    def _resolve_thread_id(self, config: RunnableConfig | None) -> str | None:
        """Extract thread_id from config.configurable."""
        if not config:
            return None
        configurable = config.get("configurable", {})
        thread_id = configurable.get("thread_id")
        return thread_id if isinstance(thread_id, str) and thread_id.strip() else None

    def _resolve_cwd(self, config: RunnableConfig | None) -> str:
        """Resolve working directory from config or fallback to default."""
        if config:
            workspace = config.get("configurable", {}).get("workspace")
            if isinstance(workspace, str) and workspace.strip():
                return str(expand_path(workspace))
        return self._cwd

    def _extract_user_text(self, input_arg: str | dict) -> str:
        """Extract user text from input.

        Args:
            input_arg: User text (str) or LangGraph state dict with 'messages' key.

        Returns:
            Extracted user text string.
        """
        if isinstance(input_arg, str):
            return input_arg

        # Dict input (LangGraph state format)
        messages = input_arg.get("messages", [])
        if not messages:
            return ""

        # Get last human message
        for msg in reversed(messages):
            if isinstance(msg, HumanMessage):
                return msg.content if isinstance(msg.content, str) else str(msg.content)

        # Fallback to last message
        last = messages[-1]
        if hasattr(last, "content"):
            return last.content if isinstance(last.content, str) else str(last.content)
        return str(last)

    def _emit_text_chunks(
        self, text: str, stream_mode: list[str] | None, thread_id: str | None
    ) -> Generator[Any, None, None]:
        """Convert TextBlock to LangGraph stream chunks.

        Args:
            text: Text content from TextBlock.
            stream_mode: Active stream modes.
            thread_id: Thread identifier.

        Yields:
            Stream chunks in requested modes.
        """
        if not stream_mode:
            return

        if "messages" in stream_mode:
            # Emit as AIMessageChunk
            chunk = AIMessageChunk(content=text)
            metadata = {"langgraph_node": "agent", "thread_id": thread_id or "unknown"}
            yield (metadata, chunk)

    def _emit_tool_use_chunks(
        self, block: Any, stream_mode: list[str] | None, thread_id: str | None
    ) -> Generator[Any, None, None]:
        """Convert ToolUseBlock to LangGraph stream chunks.

        Args:
            block: ToolUseBlock from claude-agent-sdk.
            stream_mode: Active stream modes.
            thread_id: Thread identifier.

        Yields:
            Stream chunks in requested modes.
        """
        if not stream_mode:
            return

        if "custom" in stream_mode:
            yield {
                "event": "tool_use",
                "tool": getattr(block, "name", ""),
                "input": getattr(block, "input", {}),
                "thread_id": thread_id or "unknown",
            }
