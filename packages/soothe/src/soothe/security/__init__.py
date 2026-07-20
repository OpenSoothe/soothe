"""Host security helpers (daemon kill guards, etc.)."""

from soothe.security.daemon_kill_guards import (
    PRODUCTION_DAEMON_WS_PORT,
    daemon_protected_kill_refusal,
    ensure_daemon_kill_guards_installed,
)

__all__ = [
    "PRODUCTION_DAEMON_WS_PORT",
    "daemon_protected_kill_refusal",
    "ensure_daemon_kill_guards_installed",
]
