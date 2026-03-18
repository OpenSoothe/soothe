"""CLI command groups for Soothe."""

from soothe.cli.commands.attach_cmd import attach
from soothe.cli.commands.config_cmd import config
from soothe.cli.commands.init_cmd import init_soothe
from soothe.cli.commands.run_cmd import run
from soothe.cli.commands.server_cmd import server_start, server_status, server_stop
from soothe.cli.commands.status_cmd import list_subagents, list_subagents_status, show_config
from soothe.cli.commands.thread_cmd import (
    thread_archive,
    thread_delete,
    thread_export,
    thread_inspect,
    thread_list,
    thread_resume,
)

__all__ = [
    "attach",
    "config",
    "init_soothe",
    "list_subagents",
    "list_subagents_status",
    "run",
    "server_start",
    "server_status",
    "server_stop",
    "show_config",
    "thread_archive",
    "thread_delete",
    "thread_export",
    "thread_inspect",
    "thread_list",
    "thread_resume",
]
