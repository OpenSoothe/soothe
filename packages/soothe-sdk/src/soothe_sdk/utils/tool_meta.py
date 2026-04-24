"""Canonical tool metadata registry -- single source of truth for display properties.

Every tool that appears in the CLI/TUI must have a `ToolMeta` entry here.
Adding a new tool requires adding exactly one `ToolMeta` instance;
all downstream display logic derives from the registry.

Follows the deepagents pattern of Schema + description constants: each tool's
display metadata (names, arg keys, aliases, category) is declared in one place
and consumed everywhere.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class ToolMeta:
    """Unified display metadata for a single tool.

    Attributes:
        name: Canonical snake_case tool name (e.g., ``read_file``).
        display_name: User-facing name. If ``None``, derived via
            ``name.replace("_", " ").title()`` (e.g., ``read_file`` → ``Read File``).
        arg_keys: Primary argument keys to display, in priority order.
            The first key with a non-empty value wins for one-line summaries.
        path_arg_keys: Argument keys that hold filesystem paths (subset
            of ``arg_keys``). Used for path abbreviation in display.
        aliases: Alternative names the model might emit for the same tool
            (e.g., ``shell`` and ``bash`` are aliases of ``execute``).
        category: Semantic category for output formatting
            (``file_ops``, ``execution``, ``web``, ``media``, ``goals``,
            ``subagent``, ``generic``).
        source: Origin package -- ``deepagents`` or ``soothe``.
        has_header_info: True when ``format_tool_display()`` already renders
            the key information in the header line, so the args body
            should be suppressed in ``ToolCallMessage``.
    """

    name: str
    display_name: str | None = None
    arg_keys: tuple[str, ...] = ()
    path_arg_keys: tuple[str, ...] = ()
    aliases: tuple[str, ...] = ()
    category: str = "generic"
    source: str = "soothe"
    has_header_info: bool = False

    def get_display_name(self) -> str:
        """Return the user-facing display name, with fallback."""
        if self.display_name:
            return self.display_name
        return self.name.replace("_", " ").title()


# ---------------------------------------------------------------------------
# Registry: tool name → ToolMeta (canonical name + aliases both point to same instance)
# ---------------------------------------------------------------------------

TOOL_REGISTRY: dict[str, ToolMeta] = {}


def _register(meta: ToolMeta) -> ToolMeta:
    """Insert meta into the registry under its canonical name and all aliases."""
    TOOL_REGISTRY[meta.name] = meta
    for alias in meta.aliases:
        TOOL_REGISTRY[alias] = meta
    return meta


# ---------------------------------------------------------------------------
# deepagents tools
# ---------------------------------------------------------------------------

_register(ToolMeta(
    name="read_file",
    display_name="Read File",
    arg_keys=("file_path", "path", "path_name", "target_file", "filename", "relative_path"),
    path_arg_keys=("file_path", "path", "path_name", "target_file", "filename", "relative_path"),
    category="file_ops",
    source="deepagents",
    has_header_info=True,
))

_register(ToolMeta(
    name="write_file",
    display_name="Write File",
    arg_keys=("file_path", "path"),
    path_arg_keys=("file_path", "path"),
    category="file_ops",
    source="deepagents",
    has_header_info=True,
))

_register(ToolMeta(
    name="edit_file",
    display_name="Edit File",
    arg_keys=("file_path", "path"),
    path_arg_keys=("file_path", "path"),
    category="file_ops",
    source="deepagents",
    has_header_info=True,
))

_register(ToolMeta(
    name="ls",
    display_name="List Files",
    arg_keys=("path", "path_name", "directory", "target_directory", "dir", "pattern"),
    path_arg_keys=("path", "path_name", "directory", "target_directory", "dir"),
    aliases=("list_files",),
    category="file_ops",
    source="deepagents",
    has_header_info=True,
))

_register(ToolMeta(
    name="glob",
    display_name="Search Files",
    arg_keys=("pattern", "path"),
    path_arg_keys=("path",),
    category="file_ops",
    source="deepagents",
    has_header_info=True,
))

_register(ToolMeta(
    name="grep",
    display_name="Search Content",
    arg_keys=("pattern", "regex", "regexp"),
    category="file_ops",
    source="deepagents",
    has_header_info=True,
))

_register(ToolMeta(
    name="execute",
    display_name="Shell Execute",
    arg_keys=("command", "cmd", "script"),
    aliases=("shell", "bash", "run_command"),
    category="execution",
    source="deepagents",
    has_header_info=True,
))

_register(ToolMeta(
    name="web_search",
    display_name="Web Search",
    arg_keys=("query",),
    aliases=("search_web",),
    category="web",
    source="deepagents",
    has_header_info=True,
))

_register(ToolMeta(
    name="fetch_url",
    display_name="Web Crawl",
    arg_keys=("url",),
    aliases=("crawl_web",),
    category="web",
    source="deepagents",
    has_header_info=True,
))

_register(ToolMeta(
    name="task",
    display_name="Task",
    arg_keys=("subagent_type", "description", "prompt"),
    category="subagent",
    source="deepagents",
    has_header_info=True,
))

# ---------------------------------------------------------------------------
# soothe file_ops tools
# ---------------------------------------------------------------------------

_register(ToolMeta(
    name="delete_file",
    display_name="Delete File",
    arg_keys=("file_path", "path"),
    path_arg_keys=("file_path", "path"),
    category="file_ops",
    source="soothe",
))

_register(ToolMeta(
    name="file_info",
    display_name="File Info",
    arg_keys=("path", "file_path"),
    path_arg_keys=("path", "file_path"),
    category="file_ops",
    source="soothe",
))

_register(ToolMeta(
    name="edit_file_lines",
    display_name="Edit File Lines",
    arg_keys=("path", "file_path"),
    path_arg_keys=("path", "file_path"),
    category="file_ops",
    source="soothe",
))

_register(ToolMeta(
    name="insert_lines",
    display_name="Insert Lines",
    arg_keys=("path", "file_path"),
    path_arg_keys=("path", "file_path"),
    category="file_ops",
    source="soothe",
))

_register(ToolMeta(
    name="delete_lines",
    display_name="Delete Lines",
    arg_keys=("path", "file_path"),
    path_arg_keys=("path", "file_path"),
    category="file_ops",
    source="soothe",
))

_register(ToolMeta(
    name="apply_diff",
    display_name="Apply Diff",
    arg_keys=("path", "file_path"),
    path_arg_keys=("path", "file_path"),
    category="file_ops",
    source="soothe",
))

# ---------------------------------------------------------------------------
# soothe execution tools
# ---------------------------------------------------------------------------

_register(ToolMeta(
    name="run_python",
    display_name="Run Python",
    arg_keys=("code",),
    category="execution",
    source="soothe",
))

_register(ToolMeta(
    name="run_background",
    display_name="Run Background",
    arg_keys=("command",),
    category="execution",
    source="soothe",
))

_register(ToolMeta(
    name="kill_process",
    display_name="Kill Process",
    arg_keys=("pid",),
    category="execution",
    source="soothe",
))

# ---------------------------------------------------------------------------
# soothe wizsearch tools
# ---------------------------------------------------------------------------

_register(ToolMeta(
    name="wizsearch_search",
    display_name="Multi-Engine Search",
    arg_keys=("query",),
    category="web",
    source="soothe",
    has_header_info=True,
))

_register(ToolMeta(
    name="wizsearch_crawl",
    display_name="Headless Crawl",
    arg_keys=("url",),
    category="web",
    source="soothe",
    has_header_info=True,
))

# ---------------------------------------------------------------------------
# soothe research tool
# ---------------------------------------------------------------------------

_register(ToolMeta(
    name="research",
    display_name="Research",
    arg_keys=("topic", "domain"),
    category="subagent",
    source="soothe",
    has_header_info=True,
))

# ---------------------------------------------------------------------------
# soothe media tools
# ---------------------------------------------------------------------------

_register(ToolMeta(
    name="analyze_image",
    display_name="Analyze Image",
    arg_keys=("image_path",),
    path_arg_keys=("image_path",),
    category="media",
    source="soothe",
))

_register(ToolMeta(
    name="extract_text_from_image",
    display_name="Extract Text From Image",
    arg_keys=("image_path",),
    path_arg_keys=("image_path",),
    category="media",
    source="soothe",
))

_register(ToolMeta(
    name="analyze_video",
    display_name="Analyze Video",
    arg_keys=("video_path",),
    path_arg_keys=("video_path",),
    category="media",
    source="soothe",
))

_register(ToolMeta(
    name="get_video_info",
    display_name="Get Video Info",
    arg_keys=("video_path",),
    path_arg_keys=("video_path",),
    category="media",
    source="soothe",
))

_register(ToolMeta(
    name="transcribe_audio",
    display_name="Transcribe Audio",
    arg_keys=("audio_path",),
    path_arg_keys=("audio_path",),
    category="media",
    source="soothe",
))

_register(ToolMeta(
    name="audio_qa",
    display_name="Audio QA",
    arg_keys=("audio_path",),
    path_arg_keys=("audio_path",),
    category="media",
    source="soothe",
))

# ---------------------------------------------------------------------------
# soothe data tools
# ---------------------------------------------------------------------------

_register(ToolMeta(
    name="inspect_data",
    display_name="Inspect Data",
    arg_keys=("file_path",),
    path_arg_keys=("file_path",),
    category="file_ops",
    source="soothe",
))

_register(ToolMeta(
    name="summarize_data",
    display_name="Summarize Data",
    arg_keys=("file_path",),
    path_arg_keys=("file_path",),
    category="file_ops",
    source="soothe",
))

_register(ToolMeta(
    name="check_data_quality",
    display_name="Check Data Quality",
    arg_keys=("file_path",),
    path_arg_keys=("file_path",),
    category="file_ops",
    source="soothe",
))

_register(ToolMeta(
    name="extract_text",
    display_name="Extract Text",
    arg_keys=("file_path",),
    path_arg_keys=("file_path",),
    category="file_ops",
    source="soothe",
))

_register(ToolMeta(
    name="get_data_info",
    display_name="Get Data Info",
    arg_keys=("file_path",),
    path_arg_keys=("file_path",),
    category="file_ops",
    source="soothe",
))

_register(ToolMeta(
    name="ask_about_file",
    display_name="Ask About File",
    arg_keys=("file_path",),
    path_arg_keys=("file_path",),
    category="file_ops",
    source="soothe",
))

# ---------------------------------------------------------------------------
# soothe datetime tool
# ---------------------------------------------------------------------------

_register(ToolMeta(
    name="current_datetime",
    display_name="Current DateTime",
    category="generic",
    source="soothe",
))

# ---------------------------------------------------------------------------
# soothe goals tools
# ---------------------------------------------------------------------------

_register(ToolMeta(
    name="create_goal",
    display_name="Create Goal",
    arg_keys=("description",),
    category="goals",
    source="soothe",
))

_register(ToolMeta(
    name="list_goals",
    display_name="List Goals",
    category="goals",
    source="soothe",
))

_register(ToolMeta(
    name="complete_goal",
    display_name="Complete Goal",
    arg_keys=("goal_id",),
    category="goals",
    source="soothe",
))

_register(ToolMeta(
    name="fail_goal",
    display_name="Fail Goal",
    arg_keys=("goal_id",),
    category="goals",
    source="soothe",
))

# ---------------------------------------------------------------------------
# other tools
# ---------------------------------------------------------------------------

_register(ToolMeta(
    name="ask_user",
    display_name="Ask User",
    arg_keys=("questions",),
    category="generic",
    source="soothe",
))

_register(ToolMeta(
    name="compact_conversation",
    display_name="Compact Conversation",
    category="generic",
    source="soothe",
))

_register(ToolMeta(
    name="write_todos",
    display_name="Write Todos",
    arg_keys=("todos",),
    category="generic",
    source="soothe",
    has_header_info=True,
))

# ---------------------------------------------------------------------------
# Convenience accessors (derived from registry)
# ---------------------------------------------------------------------------


def get_tool_meta(name: str) -> ToolMeta | None:
    """Look up `ToolMeta` by canonical name or any alias."""
    return TOOL_REGISTRY.get(name)


def get_tool_display_name(name: str) -> str:
    """Get user-facing display name for a tool.

    Falls back to ``name.replace("_", " ").title()`` for unknown tools,
    matching the existing SDK behavior.
    """
    meta = TOOL_REGISTRY.get(name)
    if meta:
        return meta.get_display_name()
    return name.replace("_", " ").title()


def get_all_path_arg_keys() -> frozenset[str]:
    """Return the union of all ``path_arg_keys`` across all registered tools."""
    keys: set[str] = set()
    seen_ids: set[int] = set()
    for meta in TOOL_REGISTRY.values():
        if id(meta) in seen_ids:
            continue
        seen_ids.add(id(meta))
        keys.update(meta.path_arg_keys)
    return frozenset(keys)


def get_tools_with_header_info() -> frozenset[str]:
    """Return the set of tool names where header already shows key info.

    Includes both canonical names and aliases.
    """
    seen_ids: set[int] = set()
    names: set[str] = set()
    for name, meta in TOOL_REGISTRY.items():
        if id(meta) in seen_ids:
            continue
        if meta.has_header_info:
            seen_ids.add(id(meta))
            names.add(meta.name)
            names.update(meta.aliases)
    return frozenset(names)


def get_tool_categories() -> dict[str, str]:
    """Return ``{tool_name: category}`` for all registered tools (includes aliases)."""
    return {name: meta.category for name, meta in TOOL_REGISTRY.items()}
