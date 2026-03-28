"""Shared message processing for CLI and TUI modes.

This module provides unified message handling logic to ensure consistent behavior
between headless CLI mode and the TUI interface.
"""

from __future__ import annotations

import contextlib
import json
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
    # Track pending tool calls for streaming arg accumulation (IG-053)
    # Maps tool_call_id -> {'name': str, 'args_str': str, 'emitted': bool, 'is_main': bool}
    pending_tool_calls: dict[str, dict[str, Any]] = field(default_factory=dict)
    # Track internal context for research tool filtering (IG-064)
    internal_context_active: bool = False


# ============================================================================
# Shared Tool Call Streaming Helpers (IG-053)
# ============================================================================


def accumulate_tool_call_chunks(
    pending_tool_calls: dict[str, dict[str, Any]],
    tool_call_chunks: list[dict[str, Any]],
    *,
    is_main: bool = True,
) -> None:
    """Accumulate streaming tool call chunks into pending_tool_calls.

    LangChain streams tool args in chunks - first chunk has the tool name but
    empty args, subsequent chunks contain partial JSON strings. This function
    tracks and accumulates them.

    Args:
        pending_tool_calls: Dict to store pending tool calls (tool_call_id -> state).
        tool_call_chunks: List of tool_call_chunk dicts from AIMessageChunk.
        is_main: Whether this is from the main agent.
    """
    for tcc in tool_call_chunks:
        if not isinstance(tcc, dict):
            continue
        tc_id = tcc.get("id", "")
        tc_name = tcc.get("name")
        tc_args = tcc.get("args", "")

        # First chunk with a tool name: register the pending tool call
        if tc_name and tc_id and tc_id not in pending_tool_calls:
            pending_tool_calls[tc_id] = {
                "name": tc_name,
                "args_str": tc_args if isinstance(tc_args, str) else "",
                "emitted": False,
                "is_main": is_main,
            }
        # Subsequent chunks: accumulate args
        elif tc_args and isinstance(tc_args, str):
            # Find the tool call to accumulate args for (by order, first non-emitted)
            for pending in pending_tool_calls.values():
                if not pending["emitted"]:
                    pending["args_str"] += tc_args
                    break


def try_parse_pending_tool_call_args(
    pending: dict[str, Any],
) -> dict[str, Any] | None:
    """Try to parse the accumulated args_str as JSON.

    Args:
        pending: Pending tool call state dict with 'args_str' key.

    Returns:
        Parsed args dict if valid JSON, None otherwise.
    """
    args_str = pending.get("args_str", "")
    if not args_str:
        return None
    try:
        parsed = json.loads(args_str)
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        return None


def finalize_pending_tool_call(
    pending_tool_calls: dict[str, dict[str, Any]],
    tool_call_id: str,
) -> tuple[dict[str, Any] | None, dict[str, Any], bool]:
    """Finalize and remove a pending tool call when its result arrives.

    Args:
        pending_tool_calls: Dict of pending tool calls.
        tool_call_id: ID of the tool call to finalize.

    Returns:
        Tuple of (parsed_args or None, pending_state dict, needs_emit).
        needs_emit is True if the tool call wasn't emitted yet and should be.
        If not found, returns (None, {}, False).
    """
    str_id = str(tool_call_id) if tool_call_id else ""
    if not str_id or str_id not in pending_tool_calls:
        return None, {}, False

    pending = pending_tool_calls[str_id]
    parsed_args = None
    needs_emit = not pending.get("emitted", False)

    if needs_emit:
        # Try to parse args one more time
        args_str = pending.get("args_str", "")
        if args_str:
            with contextlib.suppress(json.JSONDecodeError):
                result = json.loads(args_str)
                if isinstance(result, dict):
                    parsed_args = result
        pending["emitted"] = True

    # Clean up the pending entry
    del pending_tool_calls[str_id]
    return parsed_args, pending, needs_emit


class OutputFormatter(Protocol):
    """Protocol for pluggable output formatting."""

    def emit_assistant_text(self, text: str, *, is_main: bool) -> None:
        """Emit assistant text to the output.

        Args:
            text: The assistant text to emit.
            is_main: Whether this is from the main agent (True) or a subagent (False).
        """
        ...

    def emit_tool_call(
        self,
        name: str,
        *,
        prefix: str | None,
        is_main: bool,
        tool_call: dict[str, Any] | None = None,
        tool_call_id: str | None = None,
    ) -> None:
        """Emit a tool call notification.

        Args:
            name: The tool name being called.
            prefix: Optional namespace prefix for subagents.
            is_main: Whether this is from the main agent.
            tool_call: Optional tool call dict with args for display.
            tool_call_id: Optional unique identifier for matching with results.
        """
        ...

    def emit_tool_result(
        self,
        tool_name: str,
        brief: str,
        *,
        prefix: str | None,
        is_main: bool,
        tool_call_id: str | None = None,
    ) -> None:
        """Emit a tool result notification.

        Args:
            tool_name: The tool name that produced the result.
            brief: Brief summary of the result.
            prefix: Optional namespace prefix for subagents.
            is_main: Whether this is from the main agent.
            tool_call_id: Optional unique identifier for matching with calls.
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

        from soothe.ux.core.progress_verbosity import should_show
        from soothe.ux.core.rendering import update_name_map_from_tool_calls

        # Update name_map from tool calls
        update_name_map_from_tool_calls(msg, self.state.name_map)

        # Track seen message IDs (complete AIMessages only; chunks share ids with the final message)
        msg_id = msg.id or ""
        if not isinstance(msg, AIMessageChunk):
            if msg_id in self.state.seen_message_ids:
                return
            self.state.seen_message_ids.add(msg_id)

        raw_tcs = getattr(msg, "tool_calls", None) or []
        tcs = normalize_tool_calls_list(raw_tcs)
        has_tc_args = tool_calls_have_any_arg_dict(raw_tcs)

        # Determine if we're in a streaming chunk vs complete message
        is_chunk = isinstance(msg, AIMessageChunk)

        # Handle streaming tool args accumulation (IG-053)
        tool_call_chunks = getattr(msg, "tool_call_chunks", None) or []
        accumulate_tool_call_chunks(self.state.pending_tool_calls, tool_call_chunks, is_main=is_main)

        # Try to emit pending tool calls that have complete JSON args
        for tc_id, pending in list(self.state.pending_tool_calls.items()):
            if pending["emitted"]:
                continue
            parsed_args = try_parse_pending_tool_call_args(pending)
            if parsed_args is not None and should_show("protocol", verbosity):
                tc_display = {"args": parsed_args}
                self.formatter.emit_tool_call(
                    pending["name"],
                    prefix=None,
                    is_main=pending["is_main"],
                    tool_call=tc_display,
                    tool_call_id=tc_id,
                )
                pending["emitted"] = True

        # Process content blocks
        tool_call_emitted_from_blocks = False
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
                    # When tool_calls already have args, use that path only (see IG-053).
                    if has_tc_args:
                        continue
                    name = block.get("name", "")
                    block_tc_id = block.get("id")
                    if name and should_show("protocol", verbosity):
                        coerced = coerce_tool_call_args_to_dict(block.get("args"))
                        # Chunks often have empty/partial args before merge; prefer msg.tool_calls when present.
                        if not coerced and raw_tcs:
                            continue
                        tool_call = {"args": coerced}
                        self.formatter.emit_tool_call(
                            name,
                            prefix=None,
                            is_main=is_main,
                            tool_call=tool_call,
                            tool_call_id=block_tc_id,
                        )
                        if coerced:
                            tool_call_emitted_from_blocks = True
        elif is_main and isinstance(msg.content, str) and msg.content and should_show("assistant_text", verbosity):
            # Handle simple string content
            self._process_text_block(msg.content, is_main=is_main)

        # LangChain stores parsed args on msg.tool_calls; use when present to get full args (see IG-053).
        # For streaming chunks: only emit tool call if we have complete args (IG-053 bug fix)
        # For complete messages: always emit tool call (may have empty args for tools with defaults)
        if tcs:
            for tc in tcs:
                name = tc.get("name", "")
                tc_id = tc.get("id")
                if not name or not should_show("protocol", verbosity):
                    continue
                tc_display = dict(tc)
                tc_display["args"] = coerce_tool_call_args_to_dict(tc.get("args"))

                # Skip emitting on chunks with empty args - args will arrive in later chunks
                if is_chunk and not tc_display["args"] and not has_tc_args:
                    continue

                if has_tc_args or (not tc_display["args"] and not tool_call_emitted_from_blocks):
                    self.formatter.emit_tool_call(
                        name,
                        prefix=None,
                        is_main=is_main,
                        tool_call=tc_display,
                        tool_call_id=tc_id,
                    )

    def _process_text_block(self, text: str, *, is_main: bool) -> None:
        """Process a text block from an AI message.

        Args:
            text: The text content to process.
            is_main: Whether this is from the main agent.
        """
        # Suppress text during internal context (research tool internal LLM responses)
        if self.state.internal_context_active and not is_main:
            return

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
        from soothe.ux.core.progress_verbosity import should_show

        if not should_show("protocol", verbosity):
            return

        tool_name = getattr(msg, "name", "tool")
        tool_call_id = getattr(msg, "tool_call_id", None)
        content = msg.content if isinstance(msg.content, str) else str(msg.content)
        brief = extract_tool_brief(tool_name, content)

        # Check for pending tool call that hasn't been emitted yet (IG-053)
        parsed_args, pending, needs_emit = finalize_pending_tool_call(self.state.pending_tool_calls, tool_call_id)
        if needs_emit:
            # Emit the tool call (even with empty args)
            tc_display = {"args": parsed_args or {}}
            self.formatter.emit_tool_call(
                pending.get("name") or tool_name,
                prefix=prefix,
                is_main=pending.get("is_main", not prefix),
                tool_call=tc_display,
                tool_call_id=tool_call_id,
            )

        self.formatter.emit_tool_result(
            tool_name,
            brief,
            prefix=prefix,
            is_main=not prefix,
            tool_call_id=tool_call_id,
        )


# Shared utilities


def strip_internal_tags(text: str) -> str:
    """Strip internal tool tags from assistant text for clean display.

    Removes `<search_data>...</search_data>` blocks and associated
    synthesis instructions that should not be shown to users.
    Also filters out internal LLM JSON responses from research/inquiry engine.

    This function delegates to DisplayPolicy.filter_content() for unified
    content filtering logic using JSON parsing (not regex).

    Note: This function preserves leading/trailing whitespace to support
    streaming text chunks (e.g., " the" should keep its leading space).

    Args:
        text: The text to strip tags from.

    Returns:
        Cleaned text with internal tags removed, or empty string if
        the text is an internal LLM response that should be suppressed.
    """
    from soothe.ux.core.display_policy import DisplayPolicy

    policy = DisplayPolicy()
    text = policy._filter_json_code_blocks(text)
    text = policy._filter_plain_json(text)
    text = policy._filter_confused_responses(text)
    text = policy._filter_search_data_tags(text)
    return policy._normalize_whitespace(text)


def extract_tool_brief(tool_name: str, content: str | dict | Any, max_length: int = 120) -> str:
    r"""Extract a concise one-line summary from tool result content.

    Uses semantic formatters to provide tool-specific summaries with meaningful
    metrics (size, count, status) instead of simple truncation.

    Args:
        tool_name: Name of the tool that produced the content.
        content: Tool result content (string, dict, or ToolOutput).
        max_length: Maximum length of the brief (default 120, unused for semantic formatting).

    Returns:
        Semantic brief suitable for display.

    Example:
        >>> extract_tool_brief("read_file", "Hello\\nWorld\\n")
        "✓ Read 12 B (2 lines)"
        >>> extract_tool_brief("run_command", "output")
        "✓ Done (6 chars output)"
    """
    # Use semantic formatter for tool-specific summarization
    from soothe.ux.core.tool_output_formatter import ToolOutputFormatter

    try:
        formatter = ToolOutputFormatter()
        brief = formatter.format(tool_name, content)
        return brief.to_display()
    except Exception:
        # Fallback to simple truncation if formatter fails
        if isinstance(content, str):
            # Web search/crawl tools return structured output with summary on first line
            web_tools = {"search_web", "crawl_web"}
            if tool_name in web_tools:
                first_line = content.split("\n", 1)[0].strip()
                if first_line:
                    return first_line[:max_length]
            return content.replace("\n", " ")[:max_length]
        if isinstance(content, dict):
            # Simple dict formatting
            return f"Dict with {len(content)} fields"
        return str(content)[:max_length]


def coerce_tool_call_args_to_dict(raw: Any) -> dict[str, Any]:
    """Normalize tool arguments for display.

    ``tool_call_chunk`` content blocks use a JSON string; merged ``tool_calls`` use dicts
    (see LangChain ``ToolCall`` / ``ToolCallChunk``).
    """
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        s = raw.strip()
        if not s:
            return {}
        try:
            parsed = json.loads(s)
        except json.JSONDecodeError:
            return {}
        if isinstance(parsed, dict):
            return parsed
        return {}
    return {}


def coerce_tool_call_entry_to_dict(tc: Any) -> dict[str, Any] | None:
    """Normalize a ``tool_calls`` entry to a plain dict (handles Pydantic models)."""
    if isinstance(tc, dict):
        return tc
    model_dump = getattr(tc, "model_dump", None)
    if callable(model_dump):
        try:
            dumped = model_dump()
            if isinstance(dumped, dict):
                return dumped
        except Exception:
            return None
    return None


def normalize_tool_calls_list(raw: list[Any]) -> list[dict[str, Any]]:
    """Coerce ``msg.tool_calls`` to ``dict`` entries for display logic."""
    out: list[dict[str, Any]] = []
    for tc in raw:
        coerced = coerce_tool_call_entry_to_dict(tc)
        if coerced:
            out.append(coerced)
    return out


def tool_calls_have_any_arg_dict(tc_list: list[Any]) -> bool:
    """True if any tool call has non-empty coerced argument dict."""
    return any(coerce_tool_call_args_to_dict(tc.get("args")) for tc in normalize_tool_calls_list(tc_list))


# Argument display mapping for tool calls (see IG-053)
# Maps tool name to list of argument keys to display (supports multiple args)
_ARG_DISPLAY_MAP: dict[str, list[str]] = {
    # File operations — deepagents uses ``file_path`` for read/write/edit (see IG-053)
    "read_file": ["file_path", "path"],
    "write_file": ["file_path", "path"],
    "delete_file": ["file_path", "path"],
    "file_info": ["path", "file_path"],
    "edit_file_lines": ["path", "file_path"],
    "insert_lines": ["path", "file_path"],
    "delete_lines": ["path", "file_path"],
    "apply_diff": ["path", "file_path"],
    "edit_file": ["file_path", "path"],
    "ls": ["path", "pattern"],  # Multiple args support
    "glob": ["pattern", "path"],  # Glob tool
    "list_files": ["pattern"],
    "search_files": ["pattern"],
    # Execution - show command/code
    "run_command": ["command", "args"],  # Multiple args support
    "run_python": ["code"],
    "run_background": ["command"],
    "kill_process": ["pid"],
    "execute": ["command"],  # Alias for run_command
    # Search - show pattern/query
    "search_web": ["query"],
    "crawl_web": ["url"],
    # Research - show topic
    "research": ["topic", "domain"],
    # Media - show file path
    "analyze_image": ["image_path"],
    "analyze_video": ["video_path"],
    "transcribe_audio": ["audio_path"],
    # Goals - show description or ID
    "create_goal": ["description"],
    "complete_goal": ["goal_id"],
    "fail_goal": ["goal_id"],
}


def _normalize_tool_name_for_arg_map(tool_name: str) -> str:
    """Map API tool names (any casing) to snake_case for `_ARG_DISPLAY_MAP` lookup."""
    if not tool_name:
        return tool_name
    # PascalCase / camelCase -> snake_case; already-snake names pass through
    return re.sub(r"(?<!^)(?=[A-Z])", "_", tool_name).lower()


def format_tool_call_args(tool_name: str, tool_call: dict[str, Any]) -> str:
    """Format key tool arguments for display (see IG-053).

    Extracts the most relevant argument(s) for each tool type to show
    in activity events. Supports multiple arguments per tool.

    Path arguments are converted from deepagents workspace-relative format
    to actual OS paths and abbreviated for display.

    Args:
        tool_name: Tool name as emitted by the model (snake_case or PascalCase).
        tool_call: Tool call dict with 'args' key containing arguments

    Returns:
        Formatted argument string like "(file_name.md)" or "(/Users/dev/.../file.md, pattern)"
        Empty string if no relevant argument found

    Examples:
        >>> format_tool_call_args("read_file", {"args": {"path": "config.yml"}})
        '(config.yml)'
        >>> format_tool_call_args("read_file", {"args": '{"file_path": "/README.md"}'})
        '(/Users/dev/project/README.md)'  # Converted to OS path
        >>> format_tool_call_args("run_command", {"args": {"command": "ls", "args": "-la"}})
        '(ls, -la)'
        >>> format_tool_call_args("ls", {"args": {"path": "/tests", "pattern": "*.py"}})
        '(/Users/dev/.../tests, *.py)'  # Path converted and abbreviated
    """
    from soothe.utils.path_display import convert_and_abbreviate_path, is_path_argument

    args = coerce_tool_call_args_to_dict(tool_call.get("args"))
    if not args:
        return ""

    internal = _normalize_tool_name_for_arg_map(tool_name)
    key_args = _ARG_DISPLAY_MAP.get(internal)
    if not key_args:
        return ""

    # Extract values for all configured argument keys
    values = []
    max_value_length = 40  # Increased for 120-char terminal width
    for key_arg in key_args:
        if key_arg in args:
            value = str(args[key_arg])
            # Convert and abbreviate path arguments
            if is_path_argument(key_arg):
                value = convert_and_abbreviate_path(value, max_value_length)
            elif len(value) > max_value_length:
                # Truncate non-path long values
                value = value[: max_value_length - 3] + "..."
            values.append(value)

    if not values:
        # Model may use different arg names than _ARG_DISPLAY_MAP; still show something useful.
        if args:
            parts: list[str] = []
            for k, v in list(args.items())[:3]:
                s = str(v)
                # Convert and abbreviate path arguments
                if is_path_argument(k):
                    s = convert_and_abbreviate_path(s, max_value_length)
                elif len(s) > max_value_length:
                    s = s[: max_value_length - 3] + "..."
                parts.append(s)
            return f"({', '.join(parts)})"
        return ""

    return f"({', '.join(values)})"


def is_multi_step_plan(event: dict[str, Any]) -> bool:
    """Check if event represents a multi-step plan.

    Args:
        event: Event dictionary to check.

    Returns:
        True if this is a multi-step plan event.
    """
    from soothe.core.event_catalog import PLAN_CREATED

    return event.get("type") == PLAN_CREATED and len(event.get("steps", [])) > 1
