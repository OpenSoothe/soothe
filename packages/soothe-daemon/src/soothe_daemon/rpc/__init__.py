"""RPC command handlers for the daemon (RFC-404).

This submodule provides structured command request/response handlers for slash commands.
All handlers are prefixed with underscore as they are internal daemon functions.
"""

from soothe_daemon.rpc.handlers import (
    _cmd_autopilot_dashboard,
    _cmd_cancel,
    _cmd_clear,
    _cmd_config,
    _cmd_detach,
    _cmd_exit,
    _cmd_history,
    _cmd_memory,
    _cmd_plan,
    _cmd_policy,
    _cmd_quit,
    _cmd_resume,
    _cmd_review,
    _cmd_thread,
    _handle_command_request,
    _send_command_response,
)

__all__ = [
    "_cmd_autopilot_dashboard",
    "_cmd_cancel",
    "_cmd_clear",
    "_cmd_config",
    "_cmd_detach",
    "_cmd_exit",
    "_cmd_history",
    "_cmd_memory",
    "_cmd_plan",
    "_cmd_policy",
    "_cmd_quit",
    "_cmd_resume",
    "_cmd_review",
    "_cmd_thread",
    "_handle_command_request",
    "_send_command_response",
]
