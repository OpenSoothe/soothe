"""Registry for tool→section trigger mappings."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from soothe.plugin.registry import PluginRegistry


# Built-in tool triggers (hardcoded for core tools)
BUILTIN_TOOL_TRIGGERS: dict[str, list[str]] = {
    # File operation tools
    "read_file": ["WORKSPACE"],
    "write_file": ["WORKSPACE"],
    "glob": ["WORKSPACE"],
    "grep": ["WORKSPACE"],
    "edit_file": ["WORKSPACE"],
    "delete_file": ["WORKSPACE"],
    "insert_lines": ["WORKSPACE"],
    "apply_diff": ["WORKSPACE"],
    "file_info": ["WORKSPACE"],
    # Execution tools
    "run_command": ["WORKSPACE"],
    "run_python": ["WORKSPACE"],
    "run_background": ["WORKSPACE"],
    "kill_process": [],
    # Web tools
    "search_web": [],  # No workspace dependency
    "crawl_web": [],
    # Data tools
    "inspect_data": ["WORKSPACE"],
    "summarize_data": ["WORKSPACE"],
    "check_data_quality": ["WORKSPACE"],
    "extract_text": ["WORKSPACE"],
    "get_data_info": ["WORKSPACE"],
    "ask_about_file": ["WORKSPACE"],
    # Image/audio/video tools
    "analyze_image": [],
    "transcribe_audio": [],
    "analyze_video": [],
    # Subagents
    "browser": ["WORKSPACE", "BROWSER_CONTEXT"],
    "research": ["RESEARCH_RULES", "context"],
    "claude": [],
    # Goal management tools
    "create_goal": ["THREAD", "PROTOCOLS"],
    "list_goals": ["THREAD"],
    "complete_goal": ["THREAD"],
    "fail_goal": ["THREAD"],
    # Datetime
    "datetime": [],
}


class ToolTriggerRegistry:
    """Registry for tool→section trigger mappings.

    Tools declare which system message sections they require.
    Built-in tools have hardcoded triggers, plugins define their own.
    """

    def __init__(self, plugin_registry: PluginRegistry | None = None) -> None:
        """Initialize trigger registry.

        Args:
            plugin_registry: Optional plugin registry for plugin tool metadata.
        """
        self._plugin_registry = plugin_registry

    def get_triggered_sections(self, tool_names: list[str]) -> set[str]:
        """Get sections triggered by a set of tool names.

        Args:
            tool_names: List of tool names that were recently invoked.

        Returns:
            Set of section names that should be injected.
        """
        sections = set()

        for tool_name in tool_names:
            # Check built-in triggers first
            if tool_name in BUILTIN_TOOL_TRIGGERS:
                sections.update(BUILTIN_TOOL_TRIGGERS[tool_name])
            elif self._plugin_registry:
                # Check plugin metadata for custom tools
                tool_metadata = self._plugin_registry.get_tool_metadata(tool_name)
                if tool_metadata and "triggers" in tool_metadata:
                    sections.update(tool_metadata["triggers"])

        return sections
