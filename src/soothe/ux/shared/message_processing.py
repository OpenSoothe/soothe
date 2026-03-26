"""Shared message processing for CLI and TUI modes.

This module provides unified message handling logic to ensure consistent behavior
between headless CLI mode and the TUI interface.
"""

from __future__ import annotations

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
    ) -> None:
        """Emit a tool call notification.

        Args:
            name: The tool name being called.
            prefix: Optional namespace prefix for subagents.
            is_main: Whether this is from the main agent.
            tool_call: Optional tool call dict with args for display.
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

        from soothe.ux.shared.progress_verbosity import should_show
        from soothe.ux.shared.rendering import update_name_map_from_tool_calls

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
                    if name and should_show("protocol", verbosity):
                        coerced = coerce_tool_call_args_to_dict(block.get("args"))
                        # Chunks often have empty/partial args before merge; prefer msg.tool_calls when present.
                        if not coerced and raw_tcs:
                            continue
                        tool_call = {"args": coerced}
                        self.formatter.emit_tool_call(name, prefix=None, is_main=is_main, tool_call=tool_call)
                        if coerced:
                            tool_call_emitted_from_blocks = True
        elif is_main and isinstance(msg.content, str) and msg.content and should_show("assistant_text", verbosity):
            # Handle simple string content
            self._process_text_block(msg.content, is_main=is_main)

        # LangChain stores parsed args on msg.tool_calls; use when present to get full args (see IG-053).
        if tcs:
            for tc in tcs:
                name = tc.get("name", "")
                if not name or not should_show("protocol", verbosity):
                    continue
                tc_display = dict(tc)
                tc_display["args"] = coerce_tool_call_args_to_dict(tc.get("args"))
                if has_tc_args or (not tc_display["args"] and not tool_call_emitted_from_blocks):
                    self.formatter.emit_tool_call(name, prefix=None, is_main=is_main, tool_call=tc_display)

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
        from soothe.ux.shared.progress_verbosity import should_show

        if not should_show("protocol", verbosity):
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
        Cleaned text with internal tags removed and normalized whitespace.
    """
    result = _INTERNAL_TAG_PATTERN.sub("", text)
    result = _LEFTOVER_TAG_PATTERN.sub("", result)
    result = _SYNTHESIS_INSTRUCTION_PATTERN.sub("", result)

    # Normalize whitespace to fix concatenation issues
    # Ensure single spaces between words and proper spacing after punctuation
    result = re.sub(r"\s+", " ", result)  # Normalize multiple spaces to single
    result = re.sub(r"\s*([.!?])\s*", r"\1 ", result)  # Ensure space after punctuation
    result = re.sub(r"\s+,", ",", result)  # Remove space before comma

    return result.strip()


def extract_tool_brief(tool_name: str, content: str, max_length: int = 120) -> str:
    r"""Extract a concise one-line summary from tool result content.

    For search tools (search_web, crawl_web), the first line
    is typically a human-readable header like "20 results in 15.0s for 'query'" —
    use that instead of the raw content which may contain XML tags and source data.

    Args:
        tool_name: Name of the tool that produced the content.
        content: Tool result content as string.
        max_length: Maximum length of the brief (default 120).

    Returns:
        Truncated brief suitable for display.

    Example:
        >>> extract_tool_brief("search_web", "10 results in 1.2s for 'python'\n...more data...")
        "10 results in 1.2s for 'python'"
    """
    # Web search/crawl tools return structured output with summary on first line
    web_tools = {"search_web", "crawl_web"}
    if tool_name in web_tools:
        first_line = content.split("\n", 1)[0].strip()
        if first_line:
            return first_line[:max_length]
    return content.replace("\n", " ")[:max_length]


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

    Args:
        tool_name: Tool name as emitted by the model (snake_case or PascalCase).
        tool_call: Tool call dict with 'args' key containing arguments

    Returns:
        Formatted argument string like "(file_name.md)" or "(path, pattern)"
        Empty string if no relevant argument found

    Examples:
        >>> format_tool_call_args("read_file", {"args": {"path": "config.yml"}})
        '(config.yml)'
        >>> format_tool_call_args("read_file", {"args": '{"file_path": "/README.md"}'})
        '(/README.md)'
        >>> format_tool_call_args("run_command", {"args": {"command": "ls", "args": "-la"}})
        '(ls, -la)'
        >>> format_tool_call_args("ls", {"args": {"path": "/tests", "pattern": "*.py"}})
        '(/tests, *.py)'
    """
    args = coerce_tool_call_args_to_dict(tool_call.get("args"))
    if not args:
        return ""

    internal = _normalize_tool_name_for_arg_map(tool_name)
    key_args = _ARG_DISPLAY_MAP.get(internal)
    if not key_args:
        return ""

    # Extract values for all configured argument keys
    values = []
    for key_arg in key_args:
        if key_arg in args:
            value = str(args[key_arg])
            # Truncate long values
            max_value_length = 30
            if len(value) > max_value_length:
                value = value[:27] + "..."
            values.append(value)

    if not values:
        # Model may use different arg names than _ARG_DISPLAY_MAP; still show something useful.
        if args:
            max_value_length = 30
            parts: list[str] = []
            for _k, v in list(args.items())[:3]:
                s = str(v)
                if len(s) > max_value_length:
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
