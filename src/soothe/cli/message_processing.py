"""Shared message processing for CLI and TUI modes.

This module provides unified message handling logic to ensure consistent behavior
between headless CLI mode and the TUI interface.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    from langchain_core.messages import AIMessage, ToolMessage


@dataclass
class SharedState:
    """Common state shared between CLI and TUI modes."""

    full_response: list[str] = field(default_factory=list)
    seen_message_ids: set[str] = field(default_factory=set)
    name_map: dict[str, str] = field(default_factory=dict)
    multi_step_active: bool = False
    has_error: bool = False


class OutputFormatter(Protocol):
    """Protocol for pluggable output formatting."""

    def emit_assistant_text(self, text: str, *, is_main: bool) -> None:
        """Emit assistant text to the output.

        Args:
            text: The assistant text to emit.
            is_main: Whether this is from the main agent (True) or a subagent (False).
        """
        ...

    def emit_tool_call(self, name: str, *, prefix: str | None, is_main: bool) -> None:
        """Emit a tool call notification.

        Args:
            name: The tool name being called.
            prefix: Optional namespace prefix for subagents.
            is_main: Whether this is from the main agent.
        """
        ...

    def emit_tool_result(self, tool_name: str, brief: str, *, prefix: str | None, is_main: bool) -> None:
        """Emit a tool result notification.

        Args:
            tool_name: The tool name that produced the result.
            brief: Brief summary of the result.
            prefix: Optional namespace prefix for subagents.
            is_main: Whether this is from the main agent.
        """
        ...


class MessageProcessor:
    """Unified message processing for both CLI and TUI."""

    def __init__(self, state: SharedState, formatter: OutputFormatter) -> None:
        """Initialize the message processor.

        Args:
            state: Shared state for tracking message processing.
            formatter: Output formatter for emitting messages.
        """
        self.state = state
        self.formatter = formatter

    def process_ai_message(
        self,
        msg: AIMessage,
        *,
        is_main: bool,
        verbosity: str,
    ) -> None:
        """Process AIMessage with unified logic.

        Args:
            msg: The AI message to process.
            is_main: Whether this is from the main agent.
            verbosity: Verbosity level for filtering.
        """
        from langchain_core.messages import AIMessageChunk

        from soothe.cli.progress_verbosity import should_show
        from soothe.cli.tui_shared import update_name_map_from_tool_calls

        # Update name_map from tool calls
        update_name_map_from_tool_calls(msg, self.state.name_map)

        # Track seen message IDs
        msg_id = msg.id or ""
        if not isinstance(msg, AIMessageChunk):
            if msg_id in self.state.seen_message_ids:
                return
            self.state.seen_message_ids.add(msg_id)
        elif msg_id:
            self.state.seen_message_ids.add(msg_id)

        # Process content blocks
        if hasattr(msg, "content_blocks") and msg.content_blocks:
            for block in msg.content_blocks:
                if not isinstance(block, dict):
                    continue
                btype = block.get("type")
                if btype == "text":
                    text = block.get("text", "")
                    if text and should_show("assistant_text", verbosity):
                        self._process_text_block(text, is_main=is_main)
                elif btype in ("tool_call", "tool_call_chunk"):
                    name = block.get("name", "")
                    if name and should_show("tool_activity", verbosity):
                        # Note: prefix resolution happens in formatter
                        self.formatter.emit_tool_call(name, prefix=None, is_main=is_main)
        elif is_main and isinstance(msg.content, str) and msg.content and should_show("assistant_text", verbosity):
            # Handle simple string content
            self._process_text_block(msg.content, is_main=is_main)

    def _process_text_block(self, text: str, *, is_main: bool) -> None:
        """Process a text block from an AI message.

        Args:
            text: The text content to process.
            is_main: Whether this is from the main agent.
        """
        # Strip internal tags
        cleaned = strip_internal_tags(text)
        if not cleaned:
            return

        # Store in full_response if main agent
        if is_main:
            self.state.full_response.append(cleaned)

            # Emit only if not in multi-step plan mode
            if not self.state.multi_step_active:
                self.formatter.emit_assistant_text(cleaned, is_main=is_main)
        else:
            # Subagent text always goes through formatter
            self.formatter.emit_assistant_text(cleaned, is_main=is_main)

    def process_tool_message(
        self,
        msg: ToolMessage,
        *,
        prefix: str | None,
        verbosity: str,
    ) -> None:
        """Process ToolMessage with unified logic.

        Args:
            msg: The tool message to process.
            prefix: Optional namespace prefix for subagents.
            verbosity: Verbosity level for filtering.
        """
        from soothe.cli.progress_verbosity import should_show

        if not should_show("tool_activity", verbosity):
            return

        tool_name = getattr(msg, "name", "tool")
        content = msg.content if isinstance(msg.content, str) else str(msg.content)
        brief = extract_tool_brief(tool_name, content)

        self.formatter.emit_tool_result(tool_name, brief, prefix=prefix, is_main=not prefix)


# Shared utilities

# Patterns for stripping internal tags
_INTERNAL_TAG_PATTERN = re.compile(
    r"<search_data>.*?</search_data>\s*"
    r"(?:Synthesize the search data into a clear answer\.\s*"
    r"Do NOT reproduce raw results, source listings, or URLs\.\s*)?",
    re.DOTALL,
)
_LEFTOVER_TAG_PATTERN = re.compile(r"</?search_data>")
_SYNTHESIS_INSTRUCTION_PATTERN = re.compile(
    r"Synthesize the search data into a clear answer\.\s*"
    r"Do NOT reproduce raw results, source listings, or URLs\.\s*"
)


def strip_internal_tags(text: str) -> str:
    """Strip internal tool tags from assistant text for clean display.

    Removes `<search_data>...</search_data>` blocks and associated
    synthesis instructions that should not be shown to users.

    Args:
        text: The text to strip tags from.

    Returns:
        Cleaned text with internal tags removed.
    """
    result = _INTERNAL_TAG_PATTERN.sub("", text)
    result = _LEFTOVER_TAG_PATTERN.sub("", result)
    result = _SYNTHESIS_INSTRUCTION_PATTERN.sub("", result)
    return result.strip()


def extract_tool_brief(tool_name: str, content: str, max_length: int = 120) -> str:
    r"""Extract a concise one-line summary from tool result content.

    For search tools (wizsearch), the first line is typically a human-readable
    header like "20 results in 15.0s for 'query'" — use that instead of the raw
    content which may contain XML tags and source data.

    Args:
        tool_name: Name of the tool that produced the content.
        content: Tool result content as string.
        max_length: Maximum length of the brief (default 120).

    Returns:
        Truncated brief suitable for display.

    Example:
        >>> extract_tool_brief("wizsearch", "10 results in 1.2s for 'python'\n...more data...")
        "10 results in 1.2s for 'python'"
    """
    if tool_name.startswith("wizsearch"):
        first_line = content.split("\n", 1)[0].strip()
        if first_line:
            return first_line[:max_length]
    return content.replace("\n", " ")[:max_length]


def is_multi_step_plan(event: dict[str, Any]) -> bool:
    """Check if event represents a multi-step plan.

    Args:
        event: Event dictionary to check.

    Returns:
        True if this is a multi-step plan event.
    """
    from soothe.core.events import PLAN_CREATED

    return event.get("type") == PLAN_CREATED and len(event.get("steps", [])) > 1
