"""Canonical tool metadata registry -- single source of truth for display properties.

Every tool that appears in the CLI/TUI must have a `ToolMeta` entry here.
Adding a new tool requires adding exactly one `ToolMeta` instance;
all downstream display logic derives from the registry.

Follows the pattern of Schema + description constants: each tool's
display metadata (names, arg keys, aliases, category) is declared in one place
and consumed everywhere.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


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
            (e.g., ``shell`` and ``bash`` are legacy aliases of ``run_command``).
        category: Semantic category for display grouping
            (``file_ops``, ``execution``, ``web``, ``media``, ``goals``,
            ``subagent``, ``generic``).
        outcome_type: Outcome classification for agent reasoning
            (``file_read``, ``file_write``, ``web_search``, ``code_exec``,
            ``subagent``, ``generic``). If ``None``, derived from category.
        source: Origin package -- ``soothe_deepagents`` or ``soothe``.
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
    outcome_type: str | None = None
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
# soothe_deepagents tools
# ---------------------------------------------------------------------------

_register(
    ToolMeta(
        name="read_file",
        display_name="ReadFile",
        arg_keys=(
            "file_path",
            "path",
            "path_name",
            "target_file",
            "file",
            "filepath",
            "filename",
            "relative_path",
        ),
        path_arg_keys=(
            "file_path",
            "path",
            "path_name",
            "target_file",
            "file",
            "filepath",
            "filename",
            "relative_path",
        ),
        category="file_ops",
        outcome_type="file_read",
        source="soothe_deepagents",
        has_header_info=True,
    )
)

_register(
    ToolMeta(
        name="write_file",
        display_name="WriteFile",
        arg_keys=("file_path", "path"),
        path_arg_keys=("file_path", "path"),
        category="file_ops",
        outcome_type="file_write",
        source="soothe_deepagents",
        has_header_info=True,
    )
)

_register(
    ToolMeta(
        name="edit_file",
        display_name="EditFile",
        arg_keys=("file_path", "path"),
        path_arg_keys=("file_path", "path"),
        category="file_ops",
        outcome_type="file_write",
        source="soothe_deepagents",
        has_header_info=True,
    )
)

_register(
    ToolMeta(
        name="ls",
        display_name="ListFiles",
        arg_keys=("path", "path_name", "directory", "target_directory", "dir", "pattern"),
        path_arg_keys=("path", "path_name", "directory", "target_directory", "dir"),
        aliases=("list_files",),
        category="file_ops",
        outcome_type="file_read",
        source="soothe_deepagents",
        has_header_info=True,
    )
)

_register(
    ToolMeta(
        name="glob",
        display_name="Glob",
        arg_keys=("pattern", "path"),
        path_arg_keys=("path",),
        aliases=("search_files",),
        category="file_ops",
        outcome_type="file_read",
        source="soothe_deepagents",
        has_header_info=True,
    )
)

_register(
    ToolMeta(
        name="grep",
        display_name="Grep",
        arg_keys=(
            "pattern",
            "path",
            "file_path",
            "directory",
            "target_directory",
            "dir",
            "regex",
            "regexp",
        ),
        path_arg_keys=("path", "file_path", "directory", "target_directory", "dir"),
        category="file_ops",
        outcome_type="file_read",
        source="soothe_deepagents",
        has_header_info=True,
    )
)

# ---------------------------------------------------------------------------
# soothe execution tools
# ---------------------------------------------------------------------------

_register(
    ToolMeta(
        name="run_command",
        display_name="RunCommand",
        arg_keys=("command", "cmd", "script"),
        aliases=("shell", "bash"),
        category="execution",
        outcome_type="code_exec",
        source="soothe",
        has_header_info=True,
    )
)

_register(
    ToolMeta(
        name="web_search",
        display_name="WebSearch",
        arg_keys=("query",),
        aliases=("search_web",),
        category="web",
        outcome_type="web_search",
        source="soothe_deepagents",
        has_header_info=True,
    )
)

_register(
    ToolMeta(
        name="fetch_url",
        display_name="FetchUrl",
        arg_keys=("url",),
        aliases=("crawl_web",),
        category="web",
        outcome_type="web_search",
        source="soothe_deepagents",
        has_header_info=True,
    )
)

_register(
    ToolMeta(
        name="task",
        display_name="Task",
        arg_keys=("subagent_type", "description", "prompt"),
        category="subagent",
        outcome_type="subagent",
        source="soothe_deepagents",
        has_header_info=True,
    )
)

# ---------------------------------------------------------------------------
# soothe file_ops tools
# ---------------------------------------------------------------------------

_register(
    ToolMeta(
        name="delete_file",
        display_name="DeleteFile",
        arg_keys=("file_path", "path"),
        path_arg_keys=("file_path", "path"),
        category="file_ops",
        outcome_type="file_write",
        source="soothe",
    )
)

_register(
    ToolMeta(
        name="file_info",
        display_name="FileInfo",
        arg_keys=("path", "file_path"),
        path_arg_keys=("path", "file_path"),
        category="file_ops",
        outcome_type="file_read",
        source="soothe",
    )
)

_register(
    ToolMeta(
        name="edit_lines",
        display_name="EditFileLines",
        arg_keys=("path", "file_path"),
        path_arg_keys=("path", "file_path"),
        category="file_ops",
        outcome_type="file_write",
        source="soothe",
    )
)

_register(
    ToolMeta(
        name="insert_lines",
        display_name="InsertLines",
        arg_keys=("path", "file_path"),
        path_arg_keys=("path", "file_path"),
        category="file_ops",
        outcome_type="file_write",
        source="soothe",
    )
)

_register(
    ToolMeta(
        name="delete_lines",
        display_name="DeleteLines",
        arg_keys=("path", "file_path"),
        path_arg_keys=("path", "file_path"),
        category="file_ops",
        outcome_type="file_write",
        source="soothe",
    )
)

_register(
    ToolMeta(
        name="apply_diff",
        display_name="ApplyDiff",
        arg_keys=("path", "file_path"),
        path_arg_keys=("path", "file_path"),
        category="file_ops",
        outcome_type="file_write",
        source="soothe",
    )
)

# ---------------------------------------------------------------------------
# soothe execution tools (continued)
# ---------------------------------------------------------------------------

_register(
    ToolMeta(
        name="run_python",
        display_name="RunPython",
        arg_keys=("code",),
        category="execution",
        outcome_type="code_exec",
        source="soothe",
    )
)

_register(
    ToolMeta(
        name="run_background",
        display_name="RunBackground",
        arg_keys=("command",),
        category="execution",
        outcome_type="code_exec",
        source="soothe",
    )
)

_register(
    ToolMeta(
        name="tail_background_log",
        display_name="TailBackgroundLog",
        arg_keys=("pid", "lines"),
        category="execution",
        outcome_type="code_exec",
        source="soothe",
    )
)

_register(
    ToolMeta(
        name="kill_process",
        display_name="KillProcess",
        arg_keys=("pid",),
        category="execution",
        outcome_type="code_exec",
        source="soothe",
    )
)

# ---------------------------------------------------------------------------
# LangChain Community Requests toolkit
# ---------------------------------------------------------------------------

_register(
    ToolMeta(
        name="requests_get",
        display_name="RequestsGet",
        arg_keys=("url",),
        category="web",
        outcome_type="web_search",
        source="soothe",
    )
)

_register(
    ToolMeta(
        name="requests_delete",
        display_name="RequestsDelete",
        arg_keys=("url",),
        category="web",
        outcome_type="web_search",
        source="soothe",
    )
)

_register(
    ToolMeta(
        name="requests_post",
        display_name="RequestsPost",
        arg_keys=("text",),
        category="web",
        outcome_type="generic",
        source="soothe",
    )
)

_register(
    ToolMeta(
        name="requests_patch",
        display_name="RequestsPatch",
        arg_keys=("text",),
        category="web",
        outcome_type="generic",
        source="soothe",
    )
)

_register(
    ToolMeta(
        name="requests_put",
        display_name="RequestsPut",
        arg_keys=("text",),
        category="web",
        outcome_type="generic",
        source="soothe",
    )
)

# ---------------------------------------------------------------------------
# soothe wizsearch tools
# ---------------------------------------------------------------------------

_register(
    ToolMeta(
        name="wizsearch_search",
        display_name="WebSearch",
        arg_keys=("query",),
        category="web",
        outcome_type="web_search",
        source="soothe",
        has_header_info=True,
    )
)

_register(
    ToolMeta(
        name="wizsearch_crawl",
        display_name="HeadlessCrawl",
        arg_keys=("url",),
        category="web",
        outcome_type="web_search",
        source="soothe",
        has_header_info=True,
    )
)

# ---------------------------------------------------------------------------
# soothe deep_research subagent (invoked via task tool; not a tools.* group)
# ---------------------------------------------------------------------------

_register(
    ToolMeta(
        name="deep_research",
        display_name="Deep Research",
        arg_keys=("topic", "domain"),
        category="subagent",
        outcome_type="subagent",
        source="soothe",
        has_header_info=True,
    )
)

_register(
    ToolMeta(
        name="academic_research",
        display_name="Academic Research",
        arg_keys=("topic", "domain"),
        category="subagent",
        outcome_type="subagent",
        source="soothe",
        has_header_info=True,
    )
)

# ---------------------------------------------------------------------------
# soothe media tools
# ---------------------------------------------------------------------------

_register(
    ToolMeta(
        name="analyze_image",
        display_name="AnalyzeImage",
        arg_keys=("image_path",),
        path_arg_keys=("image_path",),
        category="media",
        outcome_type="file_read",
        source="soothe",
    )
)

_register(
    ToolMeta(
        name="extract_text_from_image",
        display_name="ExtractTextFromImage",
        arg_keys=("image_path",),
        path_arg_keys=("image_path",),
        category="media",
        outcome_type="file_read",
        source="soothe",
    )
)

_register(
    ToolMeta(
        name="analyze_video",
        display_name="AnalyzeVideo",
        arg_keys=("video_path",),
        path_arg_keys=("video_path",),
        category="media",
        outcome_type="file_read",
        source="soothe",
    )
)

_register(
    ToolMeta(
        name="get_video_info",
        display_name="GetVideoInfo",
        arg_keys=("video_path",),
        path_arg_keys=("video_path",),
        category="media",
        outcome_type="file_read",
        source="soothe",
    )
)

_register(
    ToolMeta(
        name="transcribe_audio",
        display_name="TranscribeAudio",
        arg_keys=("audio_path",),
        path_arg_keys=("audio_path",),
        category="media",
        outcome_type="file_read",
        source="soothe",
    )
)

_register(
    ToolMeta(
        name="audio_qa",
        display_name="AudioQA",
        arg_keys=("audio_path",),
        path_arg_keys=("audio_path",),
        category="media",
        outcome_type="file_read",
        source="soothe",
    )
)

# ---------------------------------------------------------------------------
# soothe data tools
# ---------------------------------------------------------------------------

_register(
    ToolMeta(
        name="inspect_data",
        display_name="InspectData",
        arg_keys=("file_path",),
        path_arg_keys=("file_path",),
        category="file_ops",
        outcome_type="file_read",
        source="soothe",
    )
)

_register(
    ToolMeta(
        name="summarize_data",
        display_name="SummarizeData",
        arg_keys=("file_path",),
        path_arg_keys=("file_path",),
        category="file_ops",
        outcome_type="file_read",
        source="soothe",
    )
)

_register(
    ToolMeta(
        name="check_data_quality",
        display_name="CheckDataQuality",
        arg_keys=("file_path",),
        path_arg_keys=("file_path",),
        category="file_ops",
        outcome_type="file_read",
        source="soothe",
    )
)

_register(
    ToolMeta(
        name="extract_text",
        display_name="ExtractText",
        arg_keys=("file_path",),
        path_arg_keys=("file_path",),
        category="file_ops",
        outcome_type="file_read",
        source="soothe",
    )
)

_register(
    ToolMeta(
        name="get_data_info",
        display_name="GetDataInfo",
        arg_keys=("file_path",),
        path_arg_keys=("file_path",),
        category="file_ops",
        outcome_type="file_read",
        source="soothe",
    )
)

_register(
    ToolMeta(
        name="ask_about_file",
        display_name="AskAboutFile",
        arg_keys=("file_path",),
        path_arg_keys=("file_path",),
        category="file_ops",
        outcome_type="file_read",
        source="soothe",
    )
)

# ---------------------------------------------------------------------------
# soothe datetime tool
# ---------------------------------------------------------------------------

_register(
    ToolMeta(
        name="current_datetime",
        display_name="CurrentDateTime",
        category="generic",
        outcome_type="generic",
        source="soothe",
    )
)

# ---------------------------------------------------------------------------
# other tools
# ---------------------------------------------------------------------------

_register(
    ToolMeta(
        name="ask_user",
        display_name="AskUser",
        arg_keys=("questions",),
        category="generic",
        outcome_type="generic",
        source="soothe",
    )
)

_register(
    ToolMeta(
        name="compact_conversation",
        display_name="CompactConversation",
        category="generic",
        outcome_type="generic",
        source="soothe",
    )
)

_register(
    ToolMeta(
        name="write_todos",
        display_name="WriteTodos",
        arg_keys=("todos",),
        category="generic",
        outcome_type="generic",
        source="soothe",
        has_header_info=True,
    )
)

# ---------------------------------------------------------------------------
# Policy / security helpers
# ---------------------------------------------------------------------------

_FALLBACK_PATH_ARG_KEYS: tuple[str, ...] = (
    "path",
    "file_path",
    "target_path",
    "directory",
    "root",
    "file",
    "filepath",
    "filename",
)


def is_policy_filesystem_tool(tool_name: str) -> bool:
    """Return True if *tool_name* is a filesystem tool subject to path policy."""
    meta = get_tool_meta(tool_name)
    if meta is not None:
        return meta.category == "file_ops"
    return tool_name.startswith("fs_")


def extract_filesystem_path_for_policy(tool_name: str, tool_args: dict[str, Any]) -> str | None:
    """Return the first non-empty path-like argument for policy checks.

    Uses ``ToolMeta.path_arg_keys`` when the tool is registered; otherwise a
    small built-in key list (and legacy ``fs_*`` tools).

    Args:
        tool_name: Invoked tool name (may be an alias).
        tool_args: Tool call arguments.

    Returns:
        A non-empty path string, or ``None`` when no candidate is present.
    """
    meta = get_tool_meta(tool_name)
    # Glob defaults to virtual search root when `path` is omitted.
    if meta and meta.name == "glob":
        raw_path = tool_args.get("path")
        if raw_path is None or (isinstance(raw_path, str) and not raw_path.strip()):
            return "/"

    keys = meta.path_arg_keys if meta and meta.path_arg_keys else _FALLBACK_PATH_ARG_KEYS
    for key in keys:
        val = tool_args.get(key)
        if val is None:
            continue
        if isinstance(val, str):
            s = val.strip()
            if s:
                return s
        s = str(val).strip()
        if s:
            return s
    return None


# ---------------------------------------------------------------------------
# Convenience accessors (derived from registry)
# ---------------------------------------------------------------------------


def get_tool_meta(name: str) -> ToolMeta | None:
    """Look up `ToolMeta` by canonical name or any alias."""
    return TOOL_REGISTRY.get(name)


def get_tool_display_name(name: str) -> str:
    """Get user-facing display name for a tool."""
    meta = TOOL_REGISTRY.get(name)
    if meta:
        return meta.get_display_name()
    # Convert snake_case to TitleCase (no spaces)
    return name.replace("_", " ").title().replace(" ", "")


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


def get_file_write_tool_names() -> frozenset[str]:
    """Return canonical tool names with ``outcome_type='file_write'``."""
    seen_ids: set[int] = set()
    names: set[str] = set()
    for meta in TOOL_REGISTRY.values():
        if id(meta) in seen_ids:
            continue
        seen_ids.add(id(meta))
        if meta.outcome_type == "file_write":
            names.add(meta.name)
    return frozenset(names)


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


def get_outcome_type(name: str) -> str:
    """Get outcome_type for a tool with fallback derivation from category.

    Args:
        name: Tool name or alias

    Returns:
        outcome_type string, derived from category if not explicitly set
    """
    meta = TOOL_REGISTRY.get(name)
    if meta and meta.outcome_type:
        return meta.outcome_type

    # Fallback: categories with uniform outcome_type
    if meta:
        category_map = {
            "execution": "code_exec",
            "web": "web_search",
            "subagent": "subagent",
            "media": "file_read",
            "goals": "generic",
            "generic": "generic",
            "file_ops": "file_read",  # Default for ambiguous category
        }
        return category_map.get(meta.category, "generic")

    return "generic"
