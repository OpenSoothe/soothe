"""CLI command groups for Soothe."""

from soothe.cli.commands.autopilot_cmd import autopilot
from soothe.cli.commands.config_cmd import config_init, config_show, config_validate
from soothe.cli.commands.server_cmd import server_attach, server_start, server_status, server_stop
from soothe.cli.commands.status_cmd import agent_list, agent_status
from soothe.cli.commands.thread_cmd import (
    thread_archive,
    thread_continue,
    thread_delete,
    thread_export,
    thread_list,
    thread_show,
)

__all__ = [
    "agent_list",
    "agent_status",
    "autopilot",
    "config_init",
    "config_show",
    "config_validate",
    "server_attach",
    "server_start",
    "server_status",
    "server_stop",
    "thread_archive",
    "thread_continue",
    "thread_delete",
    "thread_export",
    "thread_list",
    "thread_show",
]
