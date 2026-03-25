"""Tool display names for user-facing messages.

Maps internal tool names (snake_case) to user-facing display names (PascalCase)
for consistent presentation in CLI and TUI interfaces.

This module provides:
- DisplayNameRegistry: Registry for plugin-registered custom display names
- register_tool_display_name(): Public API for plugins to register names
- get_tool_display_name(): Lookup with fallback to auto-conversion

Pattern: Follows the same self-registration design as the event system
(see soothe.core.event_catalog.register_event()).
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class DisplayNameRegistry:
    """Registry for tool display names with O(1) lookup.

    Allows plugins to register custom display names for their tools
    at load time. Follows the same pattern as EventRegistry.

    Attributes:
        _names: Internal dict mapping internal names to display names.
    """

    _names: dict[str, str] = field(default_factory=dict)

    def register(self, internal_name: str, display_name: str) -> None:
        """Register a display name for a tool.

        Args:
            internal_name: Internal tool name (e.g., "read_file").
            display_name: User-facing display name (e.g., "ReadFile").
        """
        self._names[internal_name] = display_name

    def get(self, internal_name: str) -> str | None:
        """Get display name for a tool.

        Args:
            internal_name: Internal tool name.

        Returns:
            Display name if registered, None otherwise.
        """
        return self._names.get(internal_name)

    def list_all(self) -> dict[str, str]:
        """Get all registered display names.

        Returns:
            Dict mapping internal names to display names.
        """
        return dict(self._names)


# Global registry instance (similar to REGISTRY in event_catalog.py)
DISPLAY_NAME_REGISTRY = DisplayNameRegistry()


def register_tool_display_name(
    internal_name: str,
    display_name: str,
) -> None:
    """Register a custom display name for a tool.

    This is the public API for plugins to register tool display names.
    Should be called at module import time (similar to register_event()).

    **Usage**:

    ```python
    from soothe.tools.display_names import register_tool_display_name

    # In your plugin's __init__.py or events.py
    register_tool_display_name("my_custom_tool", "MyCustomTool")
    register_tool_display_name("paper_search", "PaperSearch")
    ```

    Args:
        internal_name: Tool name in snake_case (e.g., "my_custom_tool").
        display_name: User-facing display name (e.g., "MyCustomTool").
    """
    DISPLAY_NAME_REGISTRY.register(internal_name, display_name)


# Map tool internal names (snake_case) to display names (PascalCase)
# Kept for backward compatibility and reference
TOOL_DISPLAY_NAMES: dict[str, str] = {
    # File operations
    "read_file": "ReadFile",
    "write_file": "WriteFile",
    "delete_file": "DeleteFile",
    "search_files": "SearchFiles",
    "list_files": "ListFiles",
    "file_info": "FileInfo",
    "edit_file_lines": "EditFileLines",
    "insert_lines": "InsertLines",
    "delete_lines": "DeleteLines",
    "apply_diff": "ApplyDiff",
    # Execution
    "run_command": "RunCommand",
    "run_python": "RunPython",
    "run_background": "RunBackground",
    "kill_process": "KillProcess",
    # Data operations
    "inspect_data": "InspectData",
    "summarize_data": "SummarizeData",
    "check_data_quality": "CheckDataQuality",
    "extract_text": "ExtractText",
    "get_data_info": "GetDataInfo",
    "ask_about_file": "AskAboutFile",
    # Goals
    "create_goal": "CreateGoal",
    "list_goals": "ListGoals",
    "complete_goal": "CompleteGoal",
    "fail_goal": "FailGoal",
    # Web
    "search_web": "SearchWeb",
    "crawl_web": "CrawlWeb",
    # Research
    "research": "Research",
    # Media
    "analyze_image": "AnalyzeImage",
    "extract_text_from_image": "ExtractTextFromImage",
    "analyze_video": "AnalyzeVideo",
    "get_video_info": "GetVideoInfo",
    "transcribe_audio": "TranscribeAudio",
    "audio_qa": "AudioQA",
    # DateTime
    "current_datetime": "CurrentDateTime",
}


def get_tool_display_name(internal_name: str) -> str:
    """Get user-facing display name for a tool.

    Lookup order:
    1. DisplayNameRegistry (plugin-registered names)
    2. TOOL_DISPLAY_NAMES (built-in fallback dict for backward compatibility)
    3. Auto-conversion (snake_case → PascalCase)

    Args:
        internal_name: Tool name in snake_case (e.g., "read_file")

    Returns:
        PascalCase display name (e.g., "ReadFile")

    Examples:
        >>> get_tool_display_name("read_file")
        'ReadFile'
        >>> get_tool_display_name("unknown_tool")
        'UnknownTool'
    """
    # Check registry first (plugin-registered names)
    if name := DISPLAY_NAME_REGISTRY.get(internal_name):
        return name

    # Fall back to built-in dict (for backward compatibility)
    if name := TOOL_DISPLAY_NAMES.get(internal_name):
        return name

    # Auto-convert snake_case to PascalCase
    return internal_name.replace("_", " ").title().replace(" ", "")


# Register built-in tool display names at module load time
# This follows the pattern from event modules (e.g., execution/events.py:107-117)


def _register_builtin_display_names() -> None:
    """Register display names for all built-in tools."""
    # File operations
    register_tool_display_name("read_file", "ReadFile")
    register_tool_display_name("write_file", "WriteFile")
    register_tool_display_name("delete_file", "DeleteFile")
    register_tool_display_name("search_files", "SearchFiles")
    register_tool_display_name("list_files", "ListFiles")
    register_tool_display_name("file_info", "FileInfo")
    register_tool_display_name("edit_file_lines", "EditFileLines")
    register_tool_display_name("insert_lines", "InsertLines")
    register_tool_display_name("delete_lines", "DeleteLines")
    register_tool_display_name("apply_diff", "ApplyDiff")
    # Execution
    register_tool_display_name("run_command", "RunCommand")
    register_tool_display_name("run_python", "RunPython")
    register_tool_display_name("run_background", "RunBackground")
    register_tool_display_name("kill_process", "KillProcess")
    # Data operations
    register_tool_display_name("inspect_data", "InspectData")
    register_tool_display_name("summarize_data", "SummarizeData")
    register_tool_display_name("check_data_quality", "CheckDataQuality")
    register_tool_display_name("extract_text", "ExtractText")
    register_tool_display_name("get_data_info", "GetDataInfo")
    register_tool_display_name("ask_about_file", "AskAboutFile")
    # Goals
    register_tool_display_name("create_goal", "CreateGoal")
    register_tool_display_name("list_goals", "ListGoals")
    register_tool_display_name("complete_goal", "CompleteGoal")
    register_tool_display_name("fail_goal", "FailGoal")
    # Web
    register_tool_display_name("search_web", "SearchWeb")
    register_tool_display_name("crawl_web", "CrawlWeb")
    # Research
    register_tool_display_name("research", "Research")
    # Media
    register_tool_display_name("analyze_image", "AnalyzeImage")
    register_tool_display_name("extract_text_from_image", "ExtractTextFromImage")
    register_tool_display_name("analyze_video", "AnalyzeVideo")
    register_tool_display_name("get_video_info", "GetVideoInfo")
    register_tool_display_name("transcribe_audio", "TranscribeAudio")
    register_tool_display_name("audio_qa", "AudioQA")
    # DateTime
    register_tool_display_name("current_datetime", "CurrentDateTime")


# Execute registration at module load time
_register_builtin_display_names()
