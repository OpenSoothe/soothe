"""ClaudeCoreAgent - Alternative CoreAgent implementation using claude-agent-sdk.

This module provides a CoreAgent implementation that uses the Claude Code CLI
via claude-agent-sdk instead of LangGraph. It implements CoreAgentProtocol
to allow switching between LangGraph-based and Claude-based execution.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator, Generator
from contextlib import aclosing
from pathlib import Path
from typing import TYPE_CHECKING, Any

from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage

from soothe.foundation.core.agent._claude_display import claude_text_summary_for_display
from soothe.foundation.core.agent._claude_session import (
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

_TOOL_PREVIEW_MAX_LEN = 120


def _preview_claude_tool_input(tool_input: Any, *, max_len: int = _TOOL_PREVIEW_MAX_LEN) -> str:
    """Compact tool arguments for progress summaries."""
    if tool_input is None:
        return "…"
    if isinstance(tool_input, dict):
        if not tool_input:
            return "…"
        parts: list[str] = []
        for k in sorted(tool_input.keys()):
            if len(parts) >= 3:
                break
            v = tool_input[k]
            vs = str(v).replace("\n", " ").strip()
            if len(vs) > 40:
                vs = vs[:37] + "..."
            parts.append(f"{k}={vs}")
        out = ", ".join(parts)
        if len(out) > max_len:
            return out[: max_len - 1] + "…"
        return out
    s = str(tool_input).replace("\n", " ").strip()
    if not s:
        return "…"
    if len(s) > max_len:
        return s[: max_len - 1] + "…"
    return s


def _get_langgraph_configurable(config: RunnableConfig | None) -> dict[str, Any]:
    """Return configurable dict from explicit config or current LangGraph context."""
    if config:
        conf = config.get("configurable")
        if isinstance(conf, dict):
            return conf
    try:
        from langgraph.config import get_config

        cfg = get_config()
        if isinstance(cfg, dict):
            conf = cfg.get("configurable")
            return conf if isinstance(conf, dict) else {}
    except Exception:
        logger.debug("LangGraph config unavailable for Claude session bridge", exc_info=True)
    return {}


def _resolve_claude_cwd(config: RunnableConfig | None, fallback: str) -> str:
    """Pick Claude Code CLI working directory from run config or fallback."""
    configurable = _get_langgraph_configurable(config)
    workspace = configurable.get("workspace")
    if isinstance(workspace, str) and workspace.strip():
        return str(expand_path(workspace))

    try:
        from soothe.foundation.workspace import FrameworkFilesystem

        dynamic = FrameworkFilesystem.get_current_workspace()
        if dynamic is not None:
            return str(dynamic.expanduser().resolve())
    except ImportError:
        logger.debug("FrameworkFilesystem not available (soothe daemon not running)")
    except Exception:
        logger.debug("FrameworkFilesystem workspace unavailable for Claude cwd", exc_info=True)

    base = fallback.strip() if fallback.strip() else str(Path.cwd())
    return str(expand_path(base))


def _claude_sessions_from_configurable(configurable: dict[str, Any]) -> dict[str, str]:
    raw = configurable.get("claude_sessions")
    if isinstance(raw, dict):
        return {
            str(k): str(v)
            for k, v in raw.items()
            if isinstance(k, str) and isinstance(v, str) and k.strip() and v.strip()
        }
    return {}


class ClaudeCoreAgent:
    """Alternative CoreAgent implementation using claude-agent-sdk.

    Implements CoreAgentProtocol without LangGraph. Uses Claude Code CLI
    via claude-agent-sdk for full tool capabilities (file ops, bash,
    web search, MCP, subagent spawning).

    This implementation:
    - Does not use LangGraph internally
    - Manages conversation state via claude-agent-sdk sessions
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
        allowed_tools: list[str] | None = None,
        disallowed_tools: list[str] | None = None,
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
            allowed_tools: Tool names to auto-approve.
            disallowed_tools: Tool names to block.
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
        self._allowed_tools = allowed_tools
        self._disallowed_tools = disallowed_tools
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
        """
        from claude_agent_sdk import (
            AssistantMessage,
            ClaudeAgentOptions,
            ResultMessage,
            TextBlock,
            ToolUseBlock,
            query,
        )

        configurable = _get_langgraph_configurable(config)
        thread_id = self._resolve_thread_id(config, configurable)
        user_text = self._extract_user_text(input_arg)
        resolved_cwd = _resolve_claude_cwd(config, self._cwd)
        claude_sessions_cfg = _claude_sessions_from_configurable(configurable)
        durability = configurable.get("soothe_durability")

        logger.debug(
            "[ClaudeCoreAgent] Starting execution (thread=%s): %s",
            thread_id or "unknown",
            user_text[:100] if user_text else "<empty>",
        )

        options = ClaudeAgentOptions(
            permission_mode=self._permission_mode,
            max_turns=self._max_turns,
        )
        if self._model:
            options.model = self._model
        if self._system_prompt:
            options.system_prompt = self._system_prompt
        if self._allowed_tools:
            options.allowed_tools = self._allowed_tools
        if self._disallowed_tools:
            options.disallowed_tools = self._disallowed_tools
        options.cwd = resolved_cwd

        resume_sid = await resolve_resume_session_id(
            thread_id=thread_id,
            cwd=resolved_cwd,
            claude_sessions_from_config=claude_sessions_cfg,
        )
        if resume_sid:
            options.resume = resume_sid
            logger.debug("[ClaudeCoreAgent] Resuming session: %s", resume_sid)

        logger.debug(
            "[ClaudeCoreAgent] Options: model=%s, cwd=%s, permission_mode=%s, max_turns=%d",
            self._model or "<default>",
            resolved_cwd,
            self._permission_mode,
            self._max_turns,
        )

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
                                tool_input = getattr(block, "input", None)
                                for chunk in self._emit_tool_use_chunks(
                                    block, stream_mode, thread_id, tool_input
                                ):
                                    yield chunk
                    elif isinstance(message, ResultMessage):
                        cost_usd = message.total_cost_usd or 0.0
                        session_id = getattr(message, "session_id", None)
                        if isinstance(session_id, str) and not session_id.strip():
                            session_id = None
                        duration_ms = int(getattr(message, "duration_ms", 0) or 0)
                        logger.debug(
                            "[ClaudeCoreAgent] Result: cost_usd=%.4f, duration_ms=%d, session_id=%s, summary=%s",
                            cost_usd,
                            duration_ms,
                            session_id or "<none>",
                            claude_text_summary_for_display("\n".join(collected_text)) or "<none>",
                        )
        except asyncio.CancelledError:
            logger.debug("[ClaudeCoreAgent] Execution cancelled (async unwind)")
            raise
        except Exception:
            logger.exception("[ClaudeCoreAgent] Execution failed")
            collected_text.append("Claude agent encountered an error.")
        else:
            await record_claude_session(
                thread_id=thread_id,
                cwd=resolved_cwd,
                session_id=session_id,
                durability=durability,
            )

        result = "\n".join(collected_text) or "Claude task completed."
        if cost_usd > 0:
            result += f"\n\n[Cost: ${cost_usd:.4f}]"

        stream_metadata = {"langgraph_node": "agent", "thread_id": thread_id or "unknown"}
        if stream_mode and "messages" in stream_mode:
            yield ((), "messages", (AIMessage(content=result), stream_metadata))
        if stream_mode and "updates" in stream_mode:
            yield ((), "updates", {"agent": {"messages": [AIMessage(content=result)]}})

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
                - allowed_tools: Tool names to auto-approve
                - disallowed_tools: Tool names to block
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
            allowed_tools=kwargs.get("allowed_tools"),
            disallowed_tools=kwargs.get("disallowed_tools"),
            memory=kwargs.get("memory"),
            planner=kwargs.get("planner"),
            policy=kwargs.get("policy"),
        )

    def _resolve_thread_id(
        self,
        config: RunnableConfig | None,
        configurable: dict[str, Any] | None = None,
    ) -> str | None:
        """Extract thread_id from config.configurable."""
        conf = configurable if configurable is not None else _get_langgraph_configurable(config)
        thread_id = conf.get("thread_id")
        return thread_id if isinstance(thread_id, str) and thread_id.strip() else None

    def _extract_user_text(self, input_arg: str | dict) -> str:
        """Extract user text from input.

        Args:
            input_arg: User text (str) or LangGraph state dict with 'messages' key.

        Returns:
            Extracted user text string.
        """
        if isinstance(input_arg, str):
            return input_arg

        messages = input_arg.get("messages", [])
        if not messages:
            return ""

        for msg in reversed(messages):
            if isinstance(msg, HumanMessage):
                return msg.content if isinstance(msg.content, str) else str(msg.content)

        last = messages[-1]
        if hasattr(last, "content"):
            return last.content if isinstance(last.content, str) else str(last.content)
        return str(last)

    def _emit_text_chunks(
        self, text: str, stream_mode: list[str] | None, thread_id: str | None
    ) -> Generator[Any, None, None]:
        """Convert TextBlock to LangGraph stream chunks."""
        if not stream_mode:
            return

        if "messages" in stream_mode:
            chunk = AIMessageChunk(content=text)
            metadata = {"langgraph_node": "agent", "thread_id": thread_id or "unknown"}
            yield ((), "messages", (chunk, metadata))

    def _emit_tool_use_chunks(
        self,
        block: Any,
        stream_mode: list[str] | None,
        thread_id: str | None,
        tool_input: Any = None,
    ) -> Generator[Any, None, None]:
        """Convert ToolUseBlock to LangGraph stream chunks."""
        if not stream_mode:
            return

        if "custom" in stream_mode:
            yield (
                (),
                "custom",
                {
                    "event": "tool_use",
                    "tool": getattr(block, "name", ""),
                    "input": getattr(block, "input", {}),
                    "input_preview": _preview_claude_tool_input(tool_input),
                    "thread_id": thread_id or "unknown",
                },
            )


__all__ = [
    "ClaudeCoreAgent",
    "_preview_claude_tool_input",
    "_resolve_claude_cwd",
    "_get_langgraph_configurable",
]
