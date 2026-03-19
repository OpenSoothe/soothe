"""Persistent CLI shell execution with security controls.

Re-exports all public names so ``from soothe.tools.cli import X`` works.
"""

from soothe.tools._internal.cli.shell import (
    ANSI_ESCAPE,
    ShellHealthState,
    _shell_health_states,
    _shell_instances,
    cleanup_shell,
)
from soothe.tools._internal.cli.tools import (
    CheckCommandExistsTool,
    CliTool,
    GetCurrentDirTool,
    KillProcessTool,
    ListDirTool,
    RunCliBackgroundTool,
    create_cli_tools,
)

__all__ = [
    "ANSI_ESCAPE",
    "CheckCommandExistsTool",
    "CliTool",
    "GetCurrentDirTool",
    "KillProcessTool",
    "ListDirTool",
    "RunCliBackgroundTool",
    "ShellHealthState",
    "_shell_health_states",
    "_shell_instances",
    "cleanup_shell",
    "create_cli_tools",
]
