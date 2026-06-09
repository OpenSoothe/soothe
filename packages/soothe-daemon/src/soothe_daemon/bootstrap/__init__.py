"""Process startup primitives for the daemon."""

# Lazy imports to avoid heavy module loading
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


def __getattr__(name: str):
    """Lazy import modules only when accessed."""
    if name == "run_daemon":
        from soothe_daemon.bootstrap.entrypoint import run_daemon

        return run_daemon
    if name == "bootstrap_dotenv":
        from soothe_daemon.bootstrap.env import bootstrap_dotenv

        return bootstrap_dotenv
    if name == "load_dotenv_adjacent_to_yaml":
        from soothe_daemon.bootstrap.env import load_dotenv_adjacent_to_yaml

        return load_dotenv_adjacent_to_yaml
    if name == "default_daemon_log_path":
        from soothe_daemon.bootstrap.logging import default_daemon_log_path

        return default_daemon_log_path
    if name == "set_client_id":
        from soothe_daemon.bootstrap.logging import set_client_id

        return set_client_id
    if name == "set_loop_id":
        from soothe_daemon.bootstrap.logging import set_loop_id

        return set_loop_id
    if name == "pid_path":
        from soothe_daemon.bootstrap.paths import pid_path

        return pid_path
    if name == "cleanup_pid":
        from soothe_daemon.bootstrap.singleton import cleanup_pid

        return cleanup_pid
    if name == "write_pid":
        from soothe_daemon.bootstrap.singleton import write_pid

        return write_pid
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
