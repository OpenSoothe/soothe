"""Process startup primitives for the daemon."""

from soothe_daemon.bootstrap.entrypoint import run_daemon
from soothe_daemon.bootstrap.env import bootstrap_dotenv, load_dotenv_adjacent_to_yaml
from soothe_daemon.bootstrap.logging import (
    default_daemon_log_path,
    set_client_id,
    set_loop_id,
)
from soothe_daemon.bootstrap.paths import pid_path
from soothe_daemon.bootstrap.singleton import cleanup_pid, write_pid

__all__ = [
    "bootstrap_dotenv",
    "cleanup_pid",
    "default_daemon_log_path",
    "load_dotenv_adjacent_to_yaml",
    "pid_path",
    "run_daemon",
    "set_client_id",
    "set_loop_id",
    "write_pid",
]
