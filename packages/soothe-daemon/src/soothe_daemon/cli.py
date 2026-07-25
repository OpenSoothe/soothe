"""Daemon management CLI - manage Soothe daemon server."""

from __future__ import annotations

import contextlib
import os
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Annotated

import typer
from soothe_sdk.paths import SOOTHE_HOME

# Lightweight helpers - avoid heavy imports (soothe.config takes 4.4s, SootheDaemon takes 5+ seconds)
_PID_FILENAME = "soothed.pid"


def _fast_pid_path() -> Path:
    """Fast PID file path without importing soothe.config."""
    return SOOTHE_HOME / _PID_FILENAME


def _load_dotenv_if_needed() -> None:
    """Load dotenv only when actually needed (for start/doctor commands)."""
    from soothe_daemon.bootstrap.env import load_dotenv_adjacent_to_yaml

    _ensure_cli_dotenv()
    return load_dotenv_adjacent_to_yaml


def _ensure_cli_dotenv() -> None:
    """Load local project ``.env`` for every ``soothed`` subcommand."""
    from soothe_daemon.bootstrap.env import bootstrap_dotenv

    bootstrap_dotenv()


app = typer.Typer(
    name="soothed",
    help="Soothe daemon management - setup/start/stop/status/doctor",
)

# Register identity sub-app (RFC-307)
from soothe_daemon.identity_cli import app as identity_app

app.add_typer(identity_app, name="identity")


# Fast status check helpers - avoid importing SootheDaemon (5+ second import chain)
# Port comes from daemon.yml (SootheDaemonConfig), not env vars.
_DEFAULT_WS_HOST = "127.0.0.1"
_DEFAULT_WS_PORT = 8765


def _get_ws_address() -> tuple[str, int]:
    """Get WebSocket host:port from daemon config.

    Loads SootheDaemonConfig from default YAML (fast, ~50ms).
    Falls back to default 127.0.0.1:8765 if config is unavailable.
    """
    try:
        from soothe_daemon.config import SootheDaemonConfig

        cfg = SootheDaemonConfig.from_default_yaml()
        return cfg.transports.websocket.host, cfg.transports.websocket.port
    except Exception:
        return _DEFAULT_WS_HOST, _DEFAULT_WS_PORT


def _is_port_live(host: str, port: int) -> bool:
    """Fast socket probe to check if port is accepting connections."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(0.1)  # 100ms is sufficient for local check
        s.connect((host, port))
        s.close()
        return True
    except (ConnectionRefusedError, OSError, TimeoutError):
        return False


def _find_port_pid(port: int) -> int | None:
    """Find PID of process listening on a TCP port using lsof.

    Args:
        port: TCP port number.

    Returns:
        PID if found, None otherwise.
    """
    with contextlib.suppress(subprocess.TimeoutExpired, FileNotFoundError, ValueError):
        result = subprocess.run(
            ["lsof", "-i", f"TCP:{port}", "-t", "-sTCP:LISTEN"],
            capture_output=True,
            text=True,
            timeout=0.3,
            check=False,
        )
        if result.returncode == 0 and result.stdout.strip():
            pids = result.stdout.strip().split("\n")
            if pids:
                return int(pids[0])
    return None


def _fast_is_running() -> tuple[bool, bool]:
    """Check if daemon is running without heavy imports.

    Uses PID file + process check first, then falls back to port probe
    to detect orphan daemons (PID file missing but process alive on port).

    Returns:
        Tuple of (is_running, is_orphan). is_orphan is True when the
        daemon is running but the PID file is missing or stale.
    """
    pf = _fast_pid_path()
    if pf.exists():
        try:
            pid = int(pf.read_text().strip())
            os.kill(pid, 0)  # Check process exists
            return True, False
        except (ValueError, ProcessLookupError, PermissionError):
            # PID file stale, clean it up and fall through to port probe
            with contextlib.suppress(OSError):
                pf.unlink()

    # Fallback: port probe to detect orphan daemons
    host, port = _get_ws_address()
    if _is_port_live(host, port):
        return True, True

    return False, False


def _fast_find_pid() -> int | None:
    """Find PID without heavy imports.

    Checks PID file first, then falls back to lsof to find the
    process holding the configured WebSocket port.
    """
    pf = _fast_pid_path()
    if pf.exists():
        try:
            pid = int(pf.read_text().strip())
            os.kill(pid, 0)
            return pid
        except (ValueError, ProcessLookupError, PermissionError):
            with contextlib.suppress(OSError):
                pf.unlink()

    # Fallback: find PID by port using lsof
    host, port = _get_ws_address()
    return _find_port_pid(port)


@app.callback(invoke_without_command=True)
def main(ctx: typer.Context) -> None:
    """Soothe daemon server - agent runtime with WebSocket transport."""
    _ensure_cli_dotenv()
    if ctx.invoked_subcommand is None:
        typer.echo(ctx.get_help())


@app.command("start")
def daemon_start(
    config: Annotated[
        str | None,
        typer.Option("--config", "-c", help="Path to daemon configuration file."),
    ] = None,
    foreground: Annotated[
        bool,
        typer.Option("--foreground", help="Run in foreground (don't daemonize)."),
    ] = False,
) -> None:
    """Start the Soothe daemon server."""
    invocation_dir = os.getcwd()
    load_dotenv_adjacent_to_yaml = _load_dotenv_if_needed()
    from soothe_daemon.bootstrap.entrypoint import run_daemon
    from soothe_daemon.config import SootheDaemonConfig, default_daemon_config_path

    daemon_cfg = _load_daemon_config(config, SootheDaemonConfig, default_daemon_config_path)
    _apply_dotenv_for_daemon_paths(daemon_cfg, config, load_dotenv_adjacent_to_yaml)
    cfg = daemon_cfg.load_soothe_config()

    running, orphan = _fast_is_running()
    if running:
        pid = _fast_find_pid()
        pid_info = f" (PID: {pid})" if pid else ""
        orphan_info = " [orphan — PID file missing]" if orphan else ""
        typer.echo(f"Daemon is already running{pid_info}{orphan_info}.")
        raise typer.Exit(code=1)

    if foreground:
        from soothe.logging import setup_logging

        from soothe_daemon.bootstrap.logging import (
            _daemon_log_level_from_soothe_config,
            default_daemon_log_path,
            setup_daemon_logging,
        )

        typer.echo("Starting daemon in foreground...")
        setup_logging(cfg, foreground=True)
        setup_daemon_logging(
            level=_daemon_log_level_from_soothe_config(cfg),
            log_file=str(default_daemon_log_path()),
            foreground=True,
        )
        run_daemon(cfg, daemon_config=daemon_cfg, detached=False)
        return

    command = [sys.executable, "-m", "soothe_daemon", "--detached"]
    if config:
        command.extend(["--config", config])

    daemon_env = os.environ.copy()
    daemon_env["SOOTHE_DAEMON_INVOCATION_DIR"] = invocation_dir

    try:
        subprocess.Popen(  # noqa: S603
            command,
            start_new_session=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            cwd=str(SOOTHE_HOME),
            env=daemon_env,
        )
    except Exception as exc:
        typer.echo(f"Failed to start daemon: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    typer.echo("Starting daemon...")
    # Daemon initialization can take several seconds (runner + transport startup).
    # Model loading timeout is 30s; give 45s total buffer for all startup tasks.
    for _ in range(450):
        running, _ = _fast_is_running()
        if running:
            pid = _fast_find_pid()
            host, port = _get_ws_address()

            pid_str = f"PID: {pid}" if pid else "PID: unknown"
            typer.echo(f"Daemon started successfully ({pid_str}, ws://{host}:{port})")
            return
        time.sleep(0.1)

    typer.echo("Daemon process was launched but did not become ready in time.", err=True)
    raise typer.Exit(code=1)


@app.command("stop")
def daemon_stop() -> None:
    """Stop the running Soothe daemon."""
    from soothe_daemon.server import SootheDaemon

    pid = _fast_find_pid()
    if pid:
        typer.echo(f"Stopping daemon (PID: {pid})...")
    else:
        typer.echo("Stopping daemon...")

    if not SootheDaemon.stop_running():
        typer.echo("No running daemon found.")
        raise typer.Exit(code=1)

    typer.echo("Daemon stopped successfully")


@app.command("status")
def daemon_status() -> None:
    """Show soothed status (fast - no heavy imports)."""
    running, orphan = _fast_is_running()
    if not running:
        typer.echo("Daemon status: stopped")
        return

    if orphan:
        typer.echo("Daemon status: running (orphan — PID file missing)")
    else:
        typer.echo("Daemon status: running")

    # Find PID
    pid = _fast_find_pid()
    if pid:
        typer.echo(f"PID: {pid}")

    # WebSocket address (use env-configurable address)
    host, port = _get_ws_address()
    typer.echo(f"WebSocket: ws://{host}:{port}")


@app.command("restart")
def daemon_restart(
    config: Annotated[
        str | None,
        typer.Option("--config", "-c", help="Path to daemon configuration file."),
    ] = None,
) -> None:
    """Restart the Soothe daemon."""
    from soothe_daemon.server import SootheDaemon

    running, _ = _fast_is_running()
    if running:
        typer.echo("Stopping existing daemon...")
        if not SootheDaemon.stop_running():
            typer.echo("Failed to stop running daemon.", err=True)
            raise typer.Exit(code=1)

    daemon_start(config=config, foreground=False)


@app.command("doctor")
def doctor(
    config: Annotated[
        str | None,
        typer.Option("--config", "-c", help="Path to daemon configuration file."),
    ] = None,
    categories: Annotated[
        list[str] | None,
        typer.Option(
            "--category",
            help="Health check category to include. Repeat to include multiple.",
        ),
    ] = None,
    exclude: Annotated[
        list[str] | None,
        typer.Option(
            "--exclude",
            help="Health check category to skip. Repeat to exclude multiple.",
        ),
    ] = None,
    output_format: Annotated[
        str,
        typer.Option(
            "--format",
            help="Report output format: text, json, or markdown.",
            case_sensitive=False,
        ),
    ] = "text",
    output_path: Annotated[
        str | None,
        typer.Option("--output", "-o", help="Write report to file instead of stdout."),
    ] = None,
    no_color: Annotated[
        bool,
        typer.Option("--no-color", help="Disable ANSI color in text output."),
    ] = False,
    fail_on: Annotated[
        str,
        typer.Option(
            "--fail-on",
            help="Exit non-zero on threshold: never, warning, or error.",
            case_sensitive=False,
        ),
    ] = "error",
) -> None:
    """Run comprehensive health checks."""
    import asyncio

    from soothe.config import SootheConfig

    load_dotenv_adjacent_to_yaml = _load_dotenv_if_needed()
    from soothe_daemon.config import SootheDaemonConfig, default_daemon_config_path
    from soothe_daemon.health.checker import HealthChecker
    from soothe_daemon.health.formatters import format_json, format_markdown, format_text
    from soothe_daemon.health.models import CheckStatus

    format_key = output_format.lower()
    fail_key = fail_on.lower()
    if format_key not in {"text", "json", "markdown"}:
        typer.echo(
            f"Invalid format '{output_format}'. Expected one of: text, json, markdown.",
            err=True,
        )
        raise typer.Exit(code=2)
    if fail_key not in {"never", "warning", "error"}:
        typer.echo(
            f"Invalid fail-on '{fail_on}'. Expected one of: never, warning, error.",
            err=True,
        )
        raise typer.Exit(code=2)

    daemon_cfg: SootheDaemonConfig | None = None
    cfg: SootheConfig | None = None
    try:
        daemon_cfg = _load_daemon_config(config, SootheDaemonConfig, default_daemon_config_path)
        _apply_dotenv_for_daemon_paths(daemon_cfg, config, load_dotenv_adjacent_to_yaml)
        cfg = daemon_cfg.load_soothe_config()
    except Exception as exc:
        if config:
            typer.echo(f"Failed to load daemon config '{config}': {exc}", err=True)
            raise typer.Exit(code=1) from exc

    if daemon_cfg is None:
        try:
            daemon_cfg = SootheDaemonConfig()
        except Exception:
            daemon_cfg = None
    if cfg is None:
        try:
            cfg = SootheConfig()
        except Exception:
            # Keep doctor usable for baseline checks even when config parsing fails.
            cfg = None

    checker = HealthChecker(cfg, daemon_config=daemon_cfg)
    report = asyncio.run(checker.run_all_checks(categories=categories, exclude=exclude))

    if format_key == "json":
        rendered = format_json(report)
    elif format_key == "markdown":
        rendered = format_markdown(report)
    else:
        rendered = format_text(report, use_color=not no_color)

    if output_path:
        output_file = Path(output_path).expanduser()
        output_file.parent.mkdir(parents=True, exist_ok=True)
        output_file.write_text(rendered)
        typer.echo(f"Health report written to {output_file}")
    else:
        typer.echo(rendered)

    if fail_key == "warning" and _status_meets_or_exceeds(
        report.overall_status, CheckStatus.WARNING
    ):
        raise typer.Exit(code=1)
    if fail_key == "error" and _status_meets_or_exceeds(report.overall_status, CheckStatus.ERROR):
        raise typer.Exit(code=1)


@app.command("memory")
def memory_trace(
    mode: Annotated[
        str,
        typer.Option("--mode", "-m", help="Query mode: daemon, gc, snapshot, objects, compare."),
    ] = "daemon",
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Output raw JSON instead of formatted text."),
    ] = False,
) -> None:
    """Display daemon memory profiling stats (tracemalloc)."""
    import json

    running, _ = _fast_is_running()
    if not running:
        typer.echo("Daemon is not running.", err=True)
        raise typer.Exit(code=1)

    host, port = _get_ws_address()
    ws_url = f"ws://{host}:{port}"

    try:
        from soothe_daemon.admin_rpc import memory_stats as fetch_memory_stats

        timeout = 30 if mode == "objects" else 10
        data = fetch_memory_stats(ws_url, mode, timeout=timeout)
    except Exception as e:
        typer.echo(f"Failed to query daemon memory stats: {e}", err=True)
        raise typer.Exit(code=1) from e

    if json_output:
        typer.echo(json.dumps(data, indent=2, default=str))
        return

    _format_memory_output(mode, data)


def _format_memory_output(mode: str, data: dict) -> None:
    """Format memory stats as readable text."""
    stats = data.get("memory_stats", {})

    if mode == "daemon":
        rss = stats.get("rss_mb", "?")
        vsz = stats.get("vsz_mb", "?")
        traced = stats.get("tracemalloc_traced_mb", "?")
        peak = stats.get("tracemalloc_peak_mb", "?")
        typer.echo(f"RSS: {rss} MB  |  VSZ: {vsz} MB")
        typer.echo(f"Traced: {traced} MB  |  Peak: {peak} MB")

        top = stats.get("top_allocations_by_line", [])
        if top:
            typer.echo(f"\nTop allocations ({len(top)}):")
            for i, entry in enumerate(top[:15], 1):
                size = entry.get("size_mb") or entry.get("size_kb", "?")
                unit = "MB" if "size_mb" in entry else "KB"
                loc = entry.get("file", "?")
                typer.echo(f"  {i:2d}. {size:>8} {unit}  {loc}")

    elif mode == "gc":
        rss_before = stats.get("rss_before_mb", "?")
        rss_after = stats.get("rss_after_mb", "?")
        reclaimed = stats.get("rss_reclaimed_mb", "?")
        typer.echo(f"GC: RSS {rss_before} MB -> {rss_after} MB (reclaimed: {reclaimed} MB)")
        gc_stats = stats.get("gc_stats", {})
        if gc_stats:
            collections = gc_stats.get("collections", [])
            total_collected = sum(g.get("collected", 0) for g in collections)
            total_uncollectable = sum(g.get("uncollectable", 0) for g in collections)
            typer.echo(f"  collected: {total_collected}")
            typer.echo(f"  uncollectable: {total_uncollectable}")
            typer.echo(f"  garbage_count: {gc_stats.get('garbage_count', 0)}")

    elif mode == "objects":
        counts = stats.get("object_counts", {})
        if counts:
            typer.echo(f"Top object types ({len(counts)}):")
            for name, count in list(counts.items())[:20]:
                typer.echo(f"  {count:>10,}  {name}")
        else:
            typer.echo("No object counts available.")

    elif mode == "snapshot":
        _format_memory_output("daemon", data)

    elif mode == "compare":
        net_diff = stats.get("net_size_diff_kb", 0)
        typer.echo(f"Net allocation change: {net_diff:+.1f} KB")
        top_growth = stats.get("top_growth", [])
        if top_growth:
            typer.echo(f"\nTop growth ({len(top_growth)} entries):")
            for entry in top_growth[:15]:
                size = entry.get("size_diff_kb", 0)
                loc = entry.get("file", "?")
                line = entry.get("line", "")
                typer.echo(f"  {size:>+10.1f} KB  {loc}:{line}")
        top_shrink = stats.get("top_shrinkage", [])
        if top_shrink:
            typer.echo(f"\nTop shrinkage ({len(top_shrink)} entries):")
            for entry in top_shrink[:10]:
                size = entry.get("size_diff_kb", 0)
                loc = entry.get("file", "?")
                line = entry.get("line", "")
                typer.echo(f"  {size:>+10.1f} KB  {loc}:{line}")

    else:
        import json

        typer.echo(json.dumps(stats, indent=2, default=str))


@app.command("setup")
def setup_command(
    config_dir: Annotated[
        str | None,
        typer.Option(
            "--config-dir",
            help="Directory for nano.yml / soothe.yml / daemon.yml (default: $SOOTHE_HOME/config).",
        ),
    ] = None,
    yes: Annotated[
        bool,
        typer.Option(
            "--yes",
            "-y",
            help="Non-interactive: scaffold templates only; merge provider from env if present.",
        ),
    ] = False,
    force: Annotated[
        bool,
        typer.Option(
            "--force",
            help="Overwrite existing config files with packaged templates.",
        ),
    ] = False,
    skip_provider: Annotated[
        bool,
        typer.Option(
            "--skip-provider",
            help="Skip the interactive LLM provider wizard.",
        ),
    ] = False,
    skip_doctor: Annotated[
        bool,
        typer.Option(
            "--skip-doctor",
            help="Skip the post-setup provider health check.",
        ),
    ] = False,
) -> None:
    """Scaffold nano.yml / soothe.yml / daemon.yml and configure an LLM provider."""
    from soothe_daemon.setup import run_setup

    _ensure_cli_dotenv()
    code = run_setup(
        config_dir=config_dir,
        yes=yes,
        force=force,
        skip_provider=skip_provider,
        skip_doctor=skip_doctor,
    )
    if code != 0:
        raise typer.Exit(code=code)


@app.command("help")
def help_command(ctx: typer.Context) -> None:
    """Show help message and exit."""
    parent_ctx = ctx.parent if ctx.parent is not None else ctx
    typer.echo(parent_ctx.get_help())


def _apply_dotenv_for_daemon_paths(
    daemon_cfg,
    explicit_daemon_yaml: str | None,
    load_dotenv_adjacent_to_yaml,
) -> None:
    """Load ``.env`` beside daemon YAML and beside ``soothe_config_path`` before parsing agent config."""
    from soothe_daemon.config import default_daemon_config_path

    paths: list[str | Path | None] = [explicit_daemon_yaml]
    if explicit_daemon_yaml is None:
        dp = default_daemon_config_path()
        if dp.is_file():
            paths.append(dp)
    load_dotenv_adjacent_to_yaml(*paths, daemon_cfg.soothe_config_path)


def _load_daemon_config(config_path: str | None, daemon_config_cls, default_config_path_func):
    """Load ``SootheDaemonConfig`` from explicit path or default location.

    Args:
        config_path: Optional path passed from CLI (``daemon.yml``).
        daemon_config_cls: SootheDaemonConfig class (passed to avoid import).
        default_config_path_func: Function to get default config path.

    Returns:
        Parsed ``SootheDaemonConfig`` (defaults if no file found).
    """
    if config_path:
        return daemon_config_cls.from_yaml_file(config_path)

    default_config = default_config_path_func()
    if default_config.exists():
        return daemon_config_cls.from_yaml_file(default_config)
    return daemon_config_cls()


def _status_meets_or_exceeds(status: str, threshold: str) -> bool:
    """Return True when status severity is at or above the threshold."""
    from soothe_daemon.health.models import CheckStatus

    severity = {
        CheckStatus.OK: 0,
        CheckStatus.INFO: 1,
        CheckStatus.SKIPPED: 2,
        CheckStatus.WARNING: 3,
        CheckStatus.ERROR: 4,
    }
    return severity[status] >= severity[threshold]


if __name__ == "__main__":
    app()
