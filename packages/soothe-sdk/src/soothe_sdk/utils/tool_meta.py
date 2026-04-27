"""Legacy import shim for tool metadata helpers.

Canonical location: ``soothe_sdk.tools.metadata``.
"""

import re

from soothe_sdk.tools.metadata import (
    TOOL_REGISTRY,
    ToolMeta,
    get_all_path_arg_keys,
    get_outcome_type,
    get_tool_categories,
    get_tool_meta,
    get_tools_with_header_info,
)
from soothe_sdk.tools.metadata import (
    get_tool_display_name as _canonical_get_tool_display_name,
)

_LEGACY_DISPLAY_NAMES: dict[str, str] = {
    "execute": "Shell Execute",
    "ls": "List Files",
    "read_file": "Read File",
    "write_file": "Write File",
    "edit_file": "Edit File",
    "glob": "Search Files",
    "grep": "Search Content",
    "web_search": "Web Search",
    "fetch_url": "Web Crawl",
    "wizsearch_search": "Multi-Engine Search",
    "wizsearch_crawl": "Headless Crawl",
}


def get_tool_display_name(name: str) -> str:
    """Return legacy spaced display names expected by old callers/tests."""
    if name in _LEGACY_DISPLAY_NAMES:
        return _LEGACY_DISPLAY_NAMES[name]

    meta = get_tool_meta(name)
    if meta is not None and meta.name in _LEGACY_DISPLAY_NAMES:
        return _LEGACY_DISPLAY_NAMES[meta.name]

    canonical = _canonical_get_tool_display_name(name)
    if canonical == "CurrentDateTime":
        return "Current DateTime"
    if " " in canonical:
        return canonical
    # Convert PascalCase/camel tokens to spaced words.
    return re.sub(r"(?<!^)(?=[A-Z])", " ", canonical)


__all__ = [
    "ToolMeta",
    "TOOL_REGISTRY",
    "get_tool_meta",
    "get_all_path_arg_keys",
    "get_tool_display_name",
    "get_tools_with_header_info",
    "get_tool_categories",
    "get_outcome_type",
]
