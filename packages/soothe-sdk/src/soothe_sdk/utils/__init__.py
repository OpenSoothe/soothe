"""Shared utilities for SDK, CLI, and daemon.

This package provides logging, display formatting, parsing,
serde, and workspace utilities used across all Soothe packages.
"""

from soothe_sdk.utils.display import (
    convert_and_abbreviate_path,
    format_cli_error,
    get_tool_display_name,
    log_preview,
)
from soothe_sdk.utils.logging import (
    VERBOSITY_TO_LOG_LEVEL,
    GlobalInputHistory,
    resolve_cli_log_level,
    setup_logging,
)
from soothe_sdk.utils.parsing import (
    _TASK_NAME_RE,
    is_path_argument,
    parse_autopilot_goals,
    resolve_provider_env,
)
from soothe_sdk.utils.serde import (
    create_soothe_serde,
    get_soothe_msgpack_allowlist,
)
from soothe_sdk.utils.workspace import INVALID_WORKSPACE_DIRS

__all__ = [
    "setup_logging",
    "GlobalInputHistory",
    "VERBOSITY_TO_LOG_LEVEL",
    "resolve_cli_log_level",
    "format_cli_error",
    "log_preview",
    "convert_and_abbreviate_path",
    "get_tool_display_name",
    "parse_autopilot_goals",
    "_TASK_NAME_RE",
    "resolve_provider_env",
    "INVALID_WORKSPACE_DIRS",
    "is_path_argument",
    "create_soothe_serde",
    "get_soothe_msgpack_allowlist",
]
