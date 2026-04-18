"""Claude Agent subagent -- wraps claude-agent-sdk as a CompiledSubAgent.

Provides access to the full Claude Code agent capabilities: file operations,
bash execution, web search/fetch, MCP servers, and subagent spawning, all
running via the Claude Code CLI under the hood.

Requires the optional `claude` extra: `pip install soothe[claude]`
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Any

from langchain_core.messages import AIMessage
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages

from soothe.subagents.claude.events import (
    ClaudeResultEvent,
    ClaudeStartedEvent,
    ClaudeTextEvent,
    ClaudeToolUseEvent,
)
from soothe.subagents.claude.session_bridge import record_claude_session, resolve_resume_session_id
from soothe.utils import expand_path

if TYPE_CHECKING:
    from deepagents.middleware.subagents import CompiledSubAgent

logger = logging.getLogger(__name__)


def _resolve_claude_cwd(fallback: str) -> str:
    """Pick Claude Code CLI working directory (RFC-103, multi-client daemon).

    Matches tool resolution: LangGraph ``configurable.workspace`` from the parent
    run, then ``FrameworkFilesystem`` thread workspace, then factory-time fallback.

    Args:
        fallback: Directory from ``create_claude_subagent`` / ``resolve_subagents``
            when no dynamic workspace is available.

    Returns:
        Absolute path string for ``ClaudeAgentOptions.cwd``.
    """
    try:
        from langgraph.config import get_config

        cfg = get_config()
        configurable = cfg.get("configurable", {}) if isinstance(cfg, dict) else {}
        workspace = configurable.get("workspace")
        if isinstance(workspace, str) and workspace.strip():
            return str(expand_path(workspace))
    except Exception:
        logger.debug("LangGraph config workspace unavailable for Claude cwd", exc_info=True)

    try:
        from soothe.core import FrameworkFilesystem

        dynamic = FrameworkFilesystem.get_current_workspace()
        if dynamic is not None:
            return str(dynamic.expanduser().resolve())
    except Exception:
        logger.debug("FrameworkFilesystem workspace unavailable for Claude cwd", exc_info=True)

    base = fallback.strip() if fallback.strip() else str(Path.cwd())
    return str(expand_path(base))


def _get_langgraph_configurable() -> dict[str, Any]:
    """Return the current graph ``configurable`` dict, or empty."""
    try:
        from langgraph.config import get_config

        cfg = get_config()
        if isinstance(cfg, dict):
            conf = cfg.get("configurable")
            return conf if isinstance(conf, dict) else {}
    except Exception:
        logger.debug("LangGraph config unavailable for Claude session bridge", exc_info=True)
    return {}


def _get_soothe_thread_id() -> str | None:
    tid = _get_langgraph_configurable().get("thread_id")
    if isinstance(tid, str) and tid.strip():
        return tid.strip()
    return None


def _get_claude_sessions_from_config() -> dict[str, str]:
    raw = _get_langgraph_configurable().get("claude_sessions")
    if isinstance(raw, dict):
        return {
            str(k): str(v)
            for k, v in raw.items()
            if isinstance(k, str) and isinstance(v, str) and k.strip() and v.strip()
        }
    return {}


def _get_soothe_durability() -> Any | None:
    return _get_langgraph_configurable().get("soothe_durability")


CLAUDE_DESCRIPTION = (
    "Claude Code agent with full capabilities: file read/write/edit, bash execution, "
    "web search/fetch, MCP server integration, and subagent spawning. "
    "Use for: complex code analysis, multi-file refactoring, sophisticated generation tasks. "
    "DO NOT use for: simple file listing (list_files), single file reads (read_file), "
    "basic shell commands (run_command). Use direct tools instead for those operations. "
    "Requires the 'claude' extra and ANTHROPIC_API_KEY."
)


class _ClaudeState(dict):
    """State schema for the Claude subagent graph."""

    messages: Annotated[list, add_messages]


def _build_claude_graph(
    *,
    claude_model: str | None = None,
    permission_mode: str = "bypassPermissions",
    max_turns: int = 25,
    system_prompt: str | None = None,
    allowed_tools: list[str] | None = None,
    disallowed_tools: list[str] | None = None,
    cwd: str | None = None,
) -> Any:
    """Build and compile the Claude agent LangGraph.

    Args:
        claude_model: Claude model name (e.g. `sonnet`, `opus`, `haiku`).
        permission_mode: Tool permission mode for non-interactive use.
        max_turns: Maximum agent turns.
        system_prompt: Custom system prompt for the Claude agent.
        allowed_tools: Tool names to auto-approve.
        disallowed_tools: Tool names to block.
        cwd: Fallback working directory when no per-run workspace is set.

    Returns:
        Compiled LangGraph runnable.
    """

    async def _run_claude_async(state: dict[str, Any]) -> dict[str, Any]:
        from claude_agent_sdk import (
            AssistantMessage,
            ClaudeAgentOptions,
            ResultMessage,
            TextBlock,
            ToolUseBlock,
            query,
        )

        from soothe.utils.progress import emit_progress as _emit

        messages = state.get("messages", [])
        task = messages[-1].content if messages else ""

        options = ClaudeAgentOptions(
            permission_mode=permission_mode,
            max_turns=max_turns,
        )
        if claude_model:
            options.model = claude_model
        if system_prompt:
            options.system_prompt = system_prompt
        if allowed_tools:
            options.allowed_tools = allowed_tools
        if disallowed_tools:
            options.disallowed_tools = disallowed_tools
        resolved_cwd = _resolve_claude_cwd(cwd if cwd else str(Path.cwd()))
        options.cwd = resolved_cwd

        thread_id = _get_soothe_thread_id()
        claude_sessions_cfg = _get_claude_sessions_from_config()
        durability = _get_soothe_durability()
        resume_sid = await resolve_resume_session_id(
            thread_id=thread_id,
            cwd=resolved_cwd,
            claude_sessions_from_config=claude_sessions_cfg,
        )
        if resume_sid:
            options.resume = resume_sid

        _emit(
            ClaudeStartedEvent(
                task=str(task)[:500] if task else "",
                resume_session_id=resume_sid,
            ).to_dict(),
            logger,
        )

        collected_text: list[str] = []
        cost_usd: float = 0.0
        last_claude_session_id: str | None = None

        try:
            async for message in query(prompt=task, options=options):
                if isinstance(message, AssistantMessage):
                    for block in message.content:
                        if isinstance(block, TextBlock):
                            collected_text.append(block.text)
                            _emit(
                                ClaudeTextEvent(text=block.text).to_dict(),
                                logger,
                            )
                        elif isinstance(block, ToolUseBlock):
                            _emit(
                                ClaudeToolUseEvent(tool=block.name).to_dict(),
                                logger,
                            )
                elif isinstance(message, ResultMessage):
                    cost_usd = message.total_cost_usd or 0.0
                    last_claude_session_id = getattr(message, "session_id", None)
                    if (
                        isinstance(last_claude_session_id, str)
                        and not last_claude_session_id.strip()
                    ):
                        last_claude_session_id = None
                    _emit(
                        ClaudeResultEvent(
                            cost_usd=cost_usd,
                            duration_ms=int(getattr(message, "duration_ms", 0) or 0),
                            claude_session_id=last_claude_session_id,
                        ).to_dict(),
                        logger,
                    )
        except Exception:
            logger.exception("Claude agent failed")
            collected_text.append("Claude agent encountered an error.")
        else:
            await record_claude_session(
                thread_id=thread_id,
                cwd=resolved_cwd,
                session_id=last_claude_session_id,
                durability=durability,
            )

        result = "\n".join(collected_text) or "Claude task completed (no text output)."
        if cost_usd > 0:
            result += f"\n\n[Cost: ${cost_usd:.4f}]"

        return {"messages": [AIMessage(content=result)]}

    async def run_claude(state: dict[str, Any]) -> dict[str, Any]:
        """Async node that preserves LangGraph stream writer context."""
        return await _run_claude_async(state)

    graph = StateGraph(_ClaudeState)
    graph.add_node("run_claude", run_claude)
    graph.add_edge(START, "run_claude")
    graph.add_edge("run_claude", END)
    return graph.compile()


def create_claude_subagent(
    model: str | None = None,
    permission_mode: str = "bypassPermissions",
    max_turns: int = 25,
    system_prompt: str | None = None,
    allowed_tools: list[str] | None = None,
    disallowed_tools: list[str] | None = None,
    cwd: str | None = None,
    **_kwargs: Any,
) -> CompiledSubAgent:
    """Create a Claude Agent subagent (CompiledSubAgent with claude-agent-sdk).

    Args:
        model: Claude model name (e.g. `sonnet`, `opus`, `haiku`).
        permission_mode: Tool permission mode.
        max_turns: Maximum agent turns.
        system_prompt: Custom system prompt.
        allowed_tools: Tool names to auto-approve.
        disallowed_tools: Tool names to block.
        cwd: Fallback working directory when no per-run LangGraph workspace is set.
        **kwargs: Additional config (ignored for forward compat).

    Returns:
        `CompiledSubAgent` dict compatible with deepagents.
    """
    # Default to current working directory if not specified
    resolved_cwd = str(expand_path(cwd)) if cwd else str(Path.cwd())

    runnable = _build_claude_graph(
        claude_model=model,
        permission_mode=permission_mode,
        max_turns=max_turns,
        system_prompt=system_prompt,
        allowed_tools=allowed_tools,
        disallowed_tools=disallowed_tools,
        cwd=resolved_cwd,
    )

    return {
        "name": "claude",
        "description": CLAUDE_DESCRIPTION,
        "runnable": runnable,
    }
