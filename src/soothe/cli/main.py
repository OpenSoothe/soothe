"""Main CLI entry point using Typer."""

import contextlib
import json
import logging
import shutil
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Annotated, Any, Literal

import anyio
import typer

from soothe.config import SOOTHE_HOME, SootheConfig

logger = logging.getLogger(__name__)
_DAEMON_FALLBACK_EXIT_CODE = 42

app = typer.Typer(
    name="soothe",
    help="Multi-agent harness built on deepagents and langchain/langgraph.",
    add_completion=False,
)


def setup_logging(config: SootheConfig | None = None) -> None:
    """Configure the ``soothe`` logger hierarchy with a file handler.

    Writes to ``SOOTHE_HOME/logs/soothe.log`` (rotating, 10 MB max, 3 backups).

    Args:
        config: Optional config to read ``logging_config.level`` and ``logging_config.file`` from.
    """
    cfg = config or SootheConfig()
    log_dir = Path(SOOTHE_HOME) / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)

    log_file = cfg.logging.file or str(log_dir / "soothe.log")
    level_name = cfg.logging.level.upper() if cfg.logging.level else "INFO"
    if cfg.debug:
        level_name = "DEBUG"
    level = getattr(logging, level_name, logging.INFO)

    root_logger = logging.getLogger("soothe")
    if not any(isinstance(h, RotatingFileHandler) for h in root_logger.handlers):
        handler = RotatingFileHandler(log_file, maxBytes=10 * 1024 * 1024, backupCount=3, encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)-8s %(name)s %(message)s"))
        handler.setLevel(level)
        root_logger.addHandler(handler)
    root_logger.setLevel(level)

    noisy_third_party = (
        "httpx",
        "httpcore",
        "openai",
        "anthropic",
        "langchain_core",
        "langgraph",
        "browser_use",
        "bubus",
        "cdp_use",
    )
    for name in noisy_third_party:
        logging.getLogger(name).setLevel(logging.WARNING)


def migrate_sessions_to_threads() -> None:
    """Migrate old sessions/ directory to threads/ if needed.

    This is a one-time migration to support the terminology change from
    "session" to "thread" for conversation continuity.
    """
    home = Path(SOOTHE_HOME).expanduser()
    sessions_dir = home / "sessions"
    threads_dir = home / "threads"

    # Only migrate if sessions/ exists and threads/ doesn't
    if sessions_dir.exists() and not threads_dir.exists():
        try:
            sessions_dir.rename(threads_dir)
            typer.echo(f"Migrated {sessions_dir} -> {threads_dir}")
        except Exception as e:
            # Log the error but don't fail - the user can manually move if needed
            logger = logging.getLogger(__name__)
            logger.warning("Failed to migrate sessions/ to threads/: %s", e)


def migrate_rocksdb_to_data_subfolder() -> None:
    """Migrate RocksDB data files to data/ subfolders.

    This is a one-time migration to reorganize RocksDB storage structure.
    Moves existing RocksDB files from component root directories to data/ subfolders:
    - durability/ -> durability/data/
    - context/ -> context/data/
    - memory/ -> memory/data/
    """
    home = Path(SOOTHE_HOME).expanduser()

    for component in ["durability", "context", "memory"]:
        component_dir = home / component
        data_dir = component_dir / "data"

        # Skip if data/ already exists (already migrated or fresh install)
        if data_dir.exists():
            continue

        # Skip if component directory doesn't exist
        if not component_dir.exists():
            continue

        # Check for RocksDB files (*.db files, LOG, LOCK, OPTIONS*, etc.)
        rocksdb_files = []
        for pattern in ["*.db", "LOG", "LOCK", "OPTIONS*", "CURRENT", "IDENTITY", "MANIFEST-*"]:
            rocksdb_files.extend(component_dir.glob(pattern))

        # Skip if no RocksDB files found
        if not rocksdb_files:
            continue

        # Perform migration
        try:
            data_dir.mkdir(parents=True, exist_ok=True)
            for file_path in rocksdb_files:
                dest = data_dir / file_path.name
                file_path.rename(dest)
            logger = logging.getLogger(__name__)
            logger.info("Migrated %d RocksDB files from %s/ to %s/data/", len(rocksdb_files), component, component)
        except Exception as e:
            logger = logging.getLogger(__name__)
            logger.warning("Failed to migrate %s to data/ subfolder: %s", component, e)


_DEFAULT_CONFIG_PATH = Path(SOOTHE_HOME) / "config" / "config.yml"

# Config cache for performance
_config_cache: dict[str, SootheConfig] = {}


# ---------------------------------------------------------------------------
# soothe list-subagents
# ---------------------------------------------------------------------------


@app.command()
def list_subagents(
    config: Annotated[
        str | None,
        typer.Option("--config", "-c", help="Path to configuration file (YAML or JSON)."),
    ] = None,
) -> None:
    """List available subagents and their enabled/disabled status."""
    try:
        cfg = _load_config(config)

        from rich.table import Table

        from soothe.cli.commands import BUILTIN_SUBAGENT_NAMES, SUBAGENT_DISPLAY_NAMES

        table = Table(title="Available Subagents")
        table.add_column("Name", style="cyan")
        table.add_column("Technical ID", style="yellow")
        table.add_column("Status", justify="center")

        for subagent_id in BUILTIN_SUBAGENT_NAMES:
            display_name = SUBAGENT_DISPLAY_NAMES[subagent_id]
            enabled = True
            if subagent_id in cfg.subagents:
                enabled = cfg.subagents[subagent_id].enabled
            status = "[green]✓ enabled[/green]" if enabled else "[red]✗ disabled[/red]"
            table.add_row(display_name, subagent_id, status)

        typer.echo(table)

        # Also show custom subagents if any
        custom_subagents = set(cfg.subagents.keys()) - set(BUILTIN_SUBAGENT_NAMES)
        if custom_subagents:
            typer.echo("\nCustom subagents:")
            for subagent_id in sorted(custom_subagents):
                enabled = cfg.subagents[subagent_id].enabled
                status = "enabled" if enabled else "disabled"
                typer.echo(f"  - {subagent_id}: {status}")

    except KeyboardInterrupt:
        typer.echo("\nInterrupted.")
        sys.exit(0)
    except Exception as e:
        typer.echo(f"Error: {e}", err=True)
        sys.exit(1)


def _load_config(config_path: str | None) -> SootheConfig:
    """Load SootheConfig from a file path or defaults with caching.

    When no ``config_path`` is provided, automatically checks
    ``~/.soothe/config/config.yml`` and loads it if present.

    Uses an in-memory cache to avoid re-parsing config files.

    Args:
        config_path: Path to a YAML/JSON config file, or ``None`` for defaults.

    Returns:
        A ``SootheConfig`` instance.
    """
    import time

    # Determine the actual path to use
    if not config_path and _DEFAULT_CONFIG_PATH.is_file():
        config_path = str(_DEFAULT_CONFIG_PATH)

    # Use "default" as cache key when no path is provided
    cache_key = config_path or "default"

    # Check cache first
    if cache_key in _config_cache:
        logger.debug("Config loaded from cache: %s", cache_key)
        return _config_cache[cache_key]

    load_start = time.perf_counter()

    if not config_path:
        config = SootheConfig()
        _config_cache[cache_key] = config
        elapsed_ms = (time.perf_counter() - load_start) * 1000
        logger.debug("Created default config in %.1fms", elapsed_ms)
        return config

    path = Path(config_path)
    with path.open() as f:
        if config_path.endswith(".json"):
            config_data = json.load(f)
        elif config_path.endswith((".yaml", ".yml")):
            try:
                import yaml

                config_data = yaml.safe_load(f)
            except ImportError:
                typer.echo(
                    "Error: PyYAML required for YAML config files. Install: pip install pyyaml",
                    err=True,
                )
                sys.exit(1)
        else:
            typer.echo("Error: Unsupported config format. Use .yaml, .yml, or .json", err=True)
            sys.exit(1)

    config = SootheConfig(**config_data)
    _config_cache[cache_key] = config

    elapsed_ms = (time.perf_counter() - load_start) * 1000
    logger.info("Loaded config from '%s' in %.1fms", config_path, elapsed_ms)

    return config


# ---------------------------------------------------------------------------
# soothe run
# ---------------------------------------------------------------------------


@app.command()
def run(
    prompt: Annotated[
        str | None,
        typer.Argument(help="Prompt to send to the agent. Omit for interactive TUI."),
    ] = None,
    config: Annotated[
        str | None,
        typer.Option("--config", "-c", help="Path to configuration file (YAML or JSON)."),
    ] = None,
    thread: Annotated[
        str | None,
        typer.Option("--thread", "-t", help="Thread ID to resume."),
    ] = None,
    *,
    no_tui: Annotated[
        bool,
        typer.Option("--no-tui", help="Disable TUI; run single prompt and exit."),
    ] = False,
    autonomous: Annotated[
        bool,
        typer.Option("--autonomous", "-a", help="Enable autonomous iteration mode."),
    ] = False,
    max_iterations: Annotated[
        int | None,
        typer.Option("--max-iterations", help="Max iterations for autonomous mode."),
    ] = None,
    output_format: Annotated[
        str,
        typer.Option("--format", "-f", help="Output format for headless mode: text or jsonl."),
    ] = "text",
    progress_verbosity: Annotated[
        Literal["minimal", "normal", "detailed", "debug"] | None,
        typer.Option(
            "--progress-verbosity",
            help="Progress visibility: minimal, normal, detailed, debug.",
        ),
    ] = None,
) -> None:
    """Run the Soothe agent with a prompt or in interactive TUI mode."""
    import time

    startup_start = time.perf_counter()

    try:
        cfg = _load_config(config)
        if progress_verbosity is not None:
            logging_config = cfg.logging.model_copy(update={"progress_verbosity": progress_verbosity})
            cfg = cfg.model_copy(update={"logging": logging_config})
        setup_logging(cfg)
        migrate_sessions_to_threads()
        migrate_rocksdb_to_data_subfolder()

        # Check PostgreSQL availability if checkpointer is postgresql
        if cfg.protocols.durability.checkpointer == "postgresql" and not _check_postgres_available():
            logger.warning(
                "PostgreSQL checkpointer configured but server not responding at localhost:5432. "
                "Start pgvector: docker-compose up -d"
            )

        startup_elapsed_ms = (time.perf_counter() - startup_start) * 1000
        logger.info("Startup completed in %.1fms", startup_elapsed_ms)

        if prompt or no_tui:
            _run_headless(
                cfg,
                prompt or "",
                thread_id=thread,
                output_format=output_format,
                autonomous=autonomous,
                max_iterations=max_iterations,
            )
        else:
            _run_tui(cfg, thread_id=thread, config_path=config)

    except KeyboardInterrupt:
        typer.echo("\nInterrupted.")
        sys.exit(0)
    except Exception as e:
        typer.echo(f"Error: {e}", err=True)
        sys.exit(1)


def _check_postgres_available() -> bool:
    """Check if PostgreSQL is running on localhost:5432."""
    import socket

    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(1)
        result = sock.connect_ex(("localhost", 5432))
        sock.close()
    except Exception:
        return False
    else:
        return result == 0


def _run_tui(
    cfg: SootheConfig,
    *,
    thread_id: str | None = None,
    config_path: str | None = None,
) -> None:
    """Launch the Textual TUI (with daemon auto-start)."""
    try:
        from soothe.cli.tui_app import run_textual_tui

        run_textual_tui(config=cfg, thread_id=thread_id, config_path=config_path)
    except ImportError:
        typer.echo("Error: Textual is required for the TUI. Install: pip install 'textual>=0.40.0'", err=True)
        sys.exit(1)


def _run_headless(
    cfg: SootheConfig,
    prompt: str,
    *,
    thread_id: str | None = None,
    output_format: str = "text",
    autonomous: bool = False,
    max_iterations: int | None = None,
) -> None:
    """Run a single prompt with streaming output and progress events.

    Connects to running daemon if available to avoid RocksDB lock conflicts.
    Falls back to standalone mode if no daemon is running.
    """
    from soothe.cli.daemon import SootheDaemon

    if SootheDaemon.is_running():
        daemon_exit_code = _run_headless_via_daemon(
            cfg,
            prompt,
            thread_id=thread_id,
            output_format=output_format,
            autonomous=autonomous,
            max_iterations=max_iterations,
        )
        if daemon_exit_code != _DAEMON_FALLBACK_EXIT_CODE:
            sys.exit(daemon_exit_code)
        # Daemon unresponsive -- stop it to release locks, then run standalone
        typer.echo("Daemon is unresponsive, stopping it and running standalone...", err=True)
        SootheDaemon.stop_running(timeout=5.0)

    _run_headless_standalone(
        cfg,
        prompt,
        thread_id=thread_id,
        output_format=output_format,
        autonomous=autonomous,
        max_iterations=max_iterations,
    )


def _run_headless_via_daemon(
    cfg: SootheConfig,
    prompt: str,
    *,
    thread_id: str | None = None,
    output_format: str = "text",
    autonomous: bool = False,
    max_iterations: int | None = None,
) -> int:
    """Run a single prompt by connecting to a running daemon."""
    import asyncio

    from soothe.cli.daemon import DaemonClient
    from soothe.cli.progress_verbosity import classify_custom_event, should_show
    from soothe.cli.tui_shared import resolve_namespace_label, update_name_map_from_tool_calls

    async def _stream() -> int:
        _ = thread_id
        daemon_start_timeout_s = 20.0
        daemon_inactivity_timeout_s = 180.0
        client = DaemonClient()

        try:
            await asyncio.wait_for(client.connect(), timeout=5.0)

            # Send the input
            await asyncio.wait_for(
                client.send_input(
                    prompt,
                    autonomous=autonomous,
                    max_iterations=max_iterations,
                ),
                timeout=5.0,
            )

            # Stream events
            full_response: list[str] = []
            seen_message_ids: set[str] = set()
            name_map: dict[str, str] = {}
            has_error = False
            verbosity = cfg.logging.progress_verbosity
            query_started = False  # Track if we've seen the query start running

            while True:
                timeout_s = daemon_inactivity_timeout_s if query_started else daemon_start_timeout_s
                try:
                    event = await asyncio.wait_for(client.read_event(), timeout=timeout_s)
                except TimeoutError:
                    if query_started:
                        typer.echo("Error: daemon stream timed out while waiting for events.", err=True)
                        return 1
                    return _DAEMON_FALLBACK_EXIT_CODE
                if not event:
                    break

                event_type = event.get("type", "")

                # Handle status changes
                if event_type == "status":
                    state = event.get("state", "")
                    if state == "running":
                        query_started = True
                    elif (state == "idle" and query_started) or state == "stopped":
                        break
                    continue

                if event_type != "event":
                    continue

                # Detect errors before query started as a hard failure
                ev_data = event.get("data")
                if not query_started and isinstance(ev_data, dict) and ev_data.get("type") == "soothe.error":
                    typer.echo(f"Daemon error: {ev_data.get('error', 'unknown')}", err=True)
                    return 1

                namespace = tuple(event.get("namespace", []))
                mode = event.get("mode", "")
                data = event.get("data")

                if output_format == "jsonl":
                    sys.stdout.write(
                        json.dumps({"namespace": list(namespace), "mode": mode, "data": data}, default=str) + "\n"
                    )
                    sys.stdout.flush()
                    continue

                if mode == "custom" and isinstance(data, dict):
                    category = classify_custom_event(namespace, data)
                    if should_show(category, verbosity):
                        prefix = resolve_namespace_label(namespace, name_map) if namespace else None
                        _render_progress_event(data, prefix=prefix)
                    if category == "error":
                        has_error = True

                if mode == "messages":
                    message_data_tuple_length = 2
                    if not isinstance(data, (list, tuple)) or len(data) != message_data_tuple_length:
                        continue
                    msg_data, metadata = data
                    is_main = not namespace
                    if metadata and metadata.get("lc_source") == "summarization":
                        continue

                    # Reconstruct message object from serialized data
                    msg_type = msg_data.get("type") if isinstance(msg_data, dict) else None

                    # Handle AI messages (both AIMessage and AIMessageChunk)
                    if msg_type in ("ai", "AIMessage", "AIMessageChunk"):
                        msg_id = msg_data.get("id", "")

                        # Handle both content_blocks format and simple content format
                        content_blocks = msg_data.get("content_blocks", [])
                        content = msg_data.get("content", "")

                        if content_blocks and isinstance(content_blocks, list):
                            # Format 1: content_blocks array
                            update_name_map_from_tool_calls({"content_blocks": content_blocks}, name_map)

                            if msg_id:
                                if msg_id in seen_message_ids:
                                    continue
                                seen_message_ids.add(msg_id)

                            for block in content_blocks:
                                if not isinstance(block, dict):
                                    continue
                                btype = block.get("type")
                                if btype == "text":
                                    text = block.get("text", "")
                                    if is_main and text and should_show("assistant_text", verbosity):
                                        sys.stdout.write(text)
                                        sys.stdout.flush()
                                        full_response.append(text)
                                elif btype in ("tool_call", "tool_call_chunk") and should_show(
                                    "tool_activity", verbosity
                                ):
                                    name = block.get("name", "")
                                    if name:
                                        prefix = resolve_namespace_label(namespace, name_map) if namespace else None
                                        if prefix:
                                            sys.stderr.write(f"[{prefix}] [tool] Calling: {name}\n")
                                        else:
                                            sys.stderr.write(f"[tool] Calling: {name}\n")
                                        sys.stderr.flush()

                        elif content and isinstance(content, str):
                            # Format 2: simple content string (from daemon serialization)
                            if is_main and should_show("assistant_text", verbosity):
                                sys.stdout.write(content)
                                sys.stdout.flush()
                                full_response.append(content)

                    elif msg_type in ("tool", "ToolMessage") and should_show("tool_activity", verbosity):
                        tool_name = msg_data.get("name", "tool")
                        content = msg_data.get("content", "")
                        brief = content.replace("\n", " ")[:120] if isinstance(content, str) else str(content)[:120]
                        prefix = resolve_namespace_label(namespace, name_map) if namespace else None
                        if prefix:
                            sys.stderr.write(f"[{prefix}] [tool] Result ({tool_name}): {brief}\n")
                        else:
                            sys.stderr.write(f"[tool] Result ({tool_name}): {brief}\n")
                        sys.stderr.flush()

            if full_response:
                sys.stdout.write("\n")
                sys.stdout.flush()

        except (ConnectionError, OSError, TimeoutError):
            return _DAEMON_FALLBACK_EXIT_CODE
        except Exception as e:
            logger.exception("Failed to run via daemon")
            typer.echo(f"Error: {e}", err=True)
            return 1
        else:
            return 1 if has_error else 0
        finally:
            await client.close()

    return asyncio.run(_stream())


def _run_headless_standalone(
    cfg: SootheConfig,
    prompt: str,
    *,
    thread_id: str | None = None,
    output_format: str = "text",
    autonomous: bool = False,
    max_iterations: int | None = None,
) -> None:
    """Run a single prompt in standalone mode (no daemon)."""
    import asyncio

    from soothe.cli.progress_verbosity import classify_custom_event, should_show
    from soothe.cli.thread_logger import ThreadLogger
    from soothe.cli.tui_shared import resolve_namespace_label, update_name_map_from_tool_calls
    from soothe.core.runner import SootheRunner

    runner = SootheRunner(cfg)
    thread_logger = ThreadLogger(
        thread_dir=cfg.logging.thread_logging.dir,
        thread_id=thread_id or "headless",
        retention_days=cfg.logging.thread_logging.retention_days,
        max_size_mb=cfg.logging.thread_logging.max_size_mb,
    )

    _chunk_len = 3
    _msg_pair_len = 2
    exit_code = 0

    async def _stream() -> int:
        nonlocal exit_code
        from langchain_core.messages import AIMessage, AIMessageChunk, ToolMessage

        full_response: list[str] = []
        seen_message_ids: set[str] = set()
        name_map: dict[str, str] = {}
        has_error = False
        verbosity = cfg.logging.progress_verbosity

        thread_logger.log_user_input(prompt)

        stream_kwargs: dict[str, Any] = {"thread_id": thread_id}
        if autonomous:
            stream_kwargs["autonomous"] = True
            if max_iterations is not None:
                stream_kwargs["max_iterations"] = max_iterations

        try:
            async for chunk in runner.astream(prompt, **stream_kwargs):
                if not isinstance(chunk, tuple) or len(chunk) != _chunk_len:
                    continue
                namespace, mode, data = chunk

                thread_logger.log(namespace, mode, data)

                if output_format == "jsonl":
                    sys.stdout.write(
                        json.dumps({"namespace": list(namespace), "mode": mode, "data": data}, default=str) + "\n"
                    )
                    sys.stdout.flush()
                    continue

                if mode == "custom" and isinstance(data, dict):
                    category = classify_custom_event(namespace, data)
                    if should_show(category, verbosity):
                        prefix = resolve_namespace_label(namespace, name_map) if namespace else None
                        _render_progress_event(data, prefix=prefix)
                    if category == "error":
                        has_error = True

                if mode == "messages":
                    if not isinstance(data, tuple) or len(data) != _msg_pair_len:
                        continue
                    msg, metadata = data
                    is_main = not namespace
                    if metadata and metadata.get("lc_source") == "summarization":
                        continue
                    if isinstance(msg, AIMessage) and hasattr(msg, "content_blocks"):
                        update_name_map_from_tool_calls(msg, name_map)
                        msg_id = msg.id or ""
                        if not isinstance(msg, AIMessageChunk):
                            if msg_id in seen_message_ids:
                                continue
                            seen_message_ids.add(msg_id)
                        elif msg_id:
                            seen_message_ids.add(msg_id)
                        for block in msg.content_blocks:
                            if not isinstance(block, dict):
                                continue
                            btype = block.get("type")
                            if btype == "text":
                                text = block.get("text", "")
                                if is_main and text and should_show("assistant_text", verbosity):
                                    sys.stdout.write(text)
                                    sys.stdout.flush()
                                    full_response.append(text)
                            elif btype in ("tool_call", "tool_call_chunk") and should_show("tool_activity", verbosity):
                                name = block.get("name", "")
                                if name:
                                    prefix = resolve_namespace_label(namespace, name_map) if namespace else None
                                    if prefix:
                                        sys.stderr.write(f"[{prefix}] [tool] Calling: {name}\n")
                                    else:
                                        sys.stderr.write(f"[tool] Calling: {name}\n")
                                    sys.stderr.flush()
                    elif isinstance(msg, ToolMessage) and should_show("tool_activity", verbosity):
                        tool_name = getattr(msg, "name", "tool")
                        content = msg.content if isinstance(msg.content, str) else str(msg.content)
                        brief = content.replace("\n", " ")[:120]
                        prefix = resolve_namespace_label(namespace, name_map) if namespace else None
                        if prefix:
                            sys.stderr.write(f"[{prefix}] [tool] Result ({tool_name}): {brief}\n")
                        else:
                            sys.stderr.write(f"[tool] Result ({tool_name}): {brief}\n")
                        sys.stderr.flush()
            if full_response:
                sys.stdout.write("\n")
                sys.stdout.flush()
                thread_logger.log_assistant_response("".join(full_response))
            return 1 if has_error else 0
        finally:
            await runner.cleanup()

    exit_code = asyncio.run(_stream())
    sys.exit(exit_code)


# ---------------------------------------------------------------------------
# soothe config
# ---------------------------------------------------------------------------


@app.command()
def config(
    config: Annotated[
        str | None,
        typer.Option("--config", "-c", help="Path to configuration file (YAML or JSON)."),
    ] = None,
    format_output: Annotated[
        str,
        typer.Option("--format", "-f", help="Output format: json or summary."),
    ] = "summary",
) -> None:
    """Display current configuration."""
    try:
        cfg = _load_config(config)

        if format_output == "json":
            # Output full config as JSON
            import json as json_module

            config_dict = cfg.model_dump(mode="python", exclude_unset=True)
            typer.echo(json_module.dumps(config_dict, indent=2, default=str))
        else:
            # Summary output
            from rich.panel import Panel
            from rich.table import Table

            # Providers summary
            providers_table = Table(title="Model Providers")
            providers_table.add_column("Name", style="cyan")
            providers_table.add_column("Models", style="yellow")
            providers_table.add_column("Default", justify="center")

            for provider in cfg.providers:
                model_count = len(provider.models)
                providers_table.add_row(
                    provider.name,
                    f"{model_count} models",
                    "✓" if cfg.router.default.startswith(f"{provider.name}:") else "",
                )

            if not cfg.providers:
                providers_table.add_row("None configured", "", "")

            # Subagents summary
            from soothe.cli.commands import BUILTIN_SUBAGENT_NAMES, SUBAGENT_DISPLAY_NAMES

            subagents_table = Table(title="Subagents")
            subagents_table.add_column("Name", style="cyan")
            subagents_table.add_column("Status", justify="center")

            for subagent_id in BUILTIN_SUBAGENT_NAMES:
                display_name = SUBAGENT_DISPLAY_NAMES.get(subagent_id, subagent_id.replace("_", " ").title())
                enabled = True
                if subagent_id in cfg.subagents:
                    enabled = cfg.subagents[subagent_id].enabled
                status = "[green]Enabled[/green]" if enabled else "[red]Disabled[/red]"
                subagents_table.add_row(display_name, status)

            # General info
            general_table = Table(title="General Configuration")
            general_table.add_column("Setting", style="cyan")
            general_table.add_column("Value", style="yellow")
            general_table.add_row("Debug Mode", "[green]Yes[/green]" if cfg.debug else "[red]No[/red]")
            general_table.add_row("Context Backend", cfg.protocols.context.backend.title())
            general_table.add_row("Memory Backend", cfg.protocols.memory.backend.title())
            general_table.add_row("Policy Profile", cfg.protocols.policy.profile)
            general_table.add_row("Progress Verbosity", cfg.logging.progress_verbosity)
            general_table.add_row("Vector Store Provider", cfg.vector_store_provider.title())

            typer.echo(Panel(providers_table, border_style="blue"))
            typer.echo(Panel(subagents_table, border_style="blue"))
            typer.echo(Panel(general_table, border_style="blue"))

    except KeyboardInterrupt:
        typer.echo("\nInterrupted.")
        sys.exit(0)
    except Exception as e:
        typer.echo(f"Error: {e}", err=True)
        sys.exit(1)


def _render_progress_event(data: dict, *, prefix: str | None = None) -> None:
    """Render a soothe.* event as a structured progress line to stderr."""
    etype = data.get("type", "")
    if etype.startswith("soothe."):
        tag = etype.replace("soothe.", "").split(".")[0] if "." in etype else "soothe"
    elif "." in etype:
        tag = etype.split(".")[0]
    elif etype:
        tag = etype.split("_")[0]
    else:
        tag = "custom"
    parts: list[str] = []

    if etype == "soothe.context.projected":
        parts = [f"{data.get('entries', 0)} entries, {data.get('tokens', 0)} tokens"]
    elif etype == "soothe.memory.recalled":
        parts = [f"{data.get('count', 0)} items recalled"]
    elif etype == "soothe.plan.created":
        steps = data.get("steps", [])
        parts = [f"{len(steps)} steps created"]
    elif etype == "soothe.policy.checked":
        verdict = data.get("verdict", "?")
        profile = data.get("profile")
        parts = [verdict]
        if profile:
            parts.append(f"(profile={profile})")
    elif etype == "soothe.policy.denied":
        reason = data.get("reason", "denied")
        profile = data.get("profile")
        parts = [reason]
        if profile:
            parts.append(f"(profile={profile})")
    elif etype in ("soothe.thread.started", "soothe.thread.ended"):
        parts = [f"thread={data.get('thread_id', '?')}"]
    elif etype == "soothe.iteration.started":
        parts = [f"iteration {data.get('iteration', '?')}: {data.get('goal_description', '')[:60]}"]
    elif etype == "soothe.iteration.completed":
        parts = [f"iteration {data.get('iteration', '?')}: {data.get('outcome', '?')} ({data.get('duration_ms', 0)}ms)"]
    elif etype == "soothe.goal.created":
        parts = [f"{data.get('description', '')[:60]} (priority={data.get('priority', '?')})"]
    elif etype == "soothe.goal.completed":
        parts = [f"goal {data.get('goal_id', '?')} completed"]
    elif etype == "soothe.goal.failed":
        parts = [f"goal {data.get('goal_id', '?')} failed (retry {data.get('retry_count', 0)})"]
    elif etype == "soothe.error":
        parts = [data.get("error", "unknown")]
    else:
        summary_keys = ("query", "topic", "agent_name", "message", "skill_count", "result_count")
        for k in summary_keys:
            v = data.get(k)
            if v is not None:
                parts.append(f"{k}={v}")
                break

    detail = " ".join(parts) if parts else etype
    if prefix:
        sys.stderr.write(f"[{prefix}] [{tag}] {detail}\n")
    else:
        sys.stderr.write(f"[{tag}] {detail}\n")
    sys.stderr.flush()


# ---------------------------------------------------------------------------
# soothe attach
# ---------------------------------------------------------------------------


@app.command()
def attach(
    config: Annotated[
        str | None,
        typer.Option("--config", "-c", help="Path to configuration file."),
    ] = None,
    progress_verbosity: Annotated[
        Literal["minimal", "normal", "detailed", "debug"] | None,
        typer.Option(
            "--progress-verbosity",
            help="Progress visibility: minimal, normal, detailed, debug.",
        ),
    ] = None,
    thread_id: Annotated[
        str | None,
        typer.Option("--thread-id", "-t", help="Thread ID to resume."),
    ] = None,
) -> None:
    """Attach the TUI to an already-running Soothe daemon."""
    from soothe.cli.daemon import SootheDaemon

    if not SootheDaemon.is_running():
        typer.echo("Error: No Soothe daemon is running. Use 'soothe run' or 'soothe server start'.", err=True)
        sys.exit(1)

    cfg = _load_config(config)
    if progress_verbosity is not None:
        logging_config = cfg.logging.model_copy(update={"progress_verbosity": progress_verbosity})
        cfg = cfg.model_copy(update={"logging": logging_config})
    try:
        from soothe.cli.tui_app import run_textual_tui

        run_textual_tui(config=cfg, thread_id=thread_id, config_path=config)
    except ImportError:
        typer.echo("Error: Textual is required for the TUI. Install: pip install 'textual>=0.40.0'", err=True)
        sys.exit(1)


# ---------------------------------------------------------------------------
# soothe init
# ---------------------------------------------------------------------------


@app.command("init")
def init_soothe() -> None:
    """Initialize ~/.soothe with a default configuration."""
    home = Path(SOOTHE_HOME).expanduser()
    target = home / "config" / "config.yml"

    if target.exists():
        typer.echo(f"Config already exists at {target}")
        return

    template = Path(__file__).resolve().parent.parent.parent.parent / "config" / "config.yml"

    target.parent.mkdir(parents=True, exist_ok=True)
    if template.exists():
        shutil.copy2(template, target)
        typer.echo(f"Created {target}")
    else:
        target.write_text("# Soothe configuration\n# See docs/user_guide.md for options\n")
        typer.echo(f"Created minimal {target}")

    # Migrate old sessions/ to threads/ if needed
    migrate_sessions_to_threads()

    for subdir in ("threads", "generated_agents", "logs"):
        (home / subdir).mkdir(parents=True, exist_ok=True)

    typer.echo(f"Soothe home initialized at {home}")


# ---------------------------------------------------------------------------
# soothe server
# ---------------------------------------------------------------------------

server_app = typer.Typer(name="server", help="Manage the Soothe daemon process.")
app.add_typer(server_app)


@server_app.command("start")
def server_start(
    config: Annotated[
        str | None,
        typer.Option("--config", "-c", help="Path to configuration file."),
    ] = None,
    *,
    foreground: Annotated[
        bool,
        typer.Option("--foreground", help="Run in foreground (don't daemonize)."),
    ] = False,
) -> None:
    """Start the Soothe daemon."""
    import time

    from soothe.cli.daemon import SootheDaemon, pid_path, run_daemon

    if SootheDaemon.is_running():
        typer.echo("Soothe daemon is already running.")
        return

    cfg = _load_config(config)
    setup_logging(cfg)

    if foreground:
        run_daemon(cfg)
    else:
        import subprocess

        cmd = [sys.executable, "-m", "soothe.cli.daemon"]
        if config:
            cmd.extend(["--config", config])
        log_file = Path(SOOTHE_HOME) / "logs" / "daemon.stderr"
        log_file.parent.mkdir(parents=True, exist_ok=True)
        with log_file.open("a") as stderr_file:
            subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=stderr_file,
                start_new_session=True,
            )
        # Wait briefly for daemon to acquire PID lock and write PID file
        for _ in range(30):
            if pid_path().exists():
                break
            time.sleep(0.2)
        if SootheDaemon.is_running():
            pid = pid_path().read_text().strip()
            typer.echo(f"Soothe daemon started in background (PID: {pid}).")
        else:
            typer.echo("Soothe daemon started in background.")


@server_app.command("stop")
def server_stop() -> None:
    """Stop the running Soothe daemon."""
    from soothe.cli.daemon import SootheDaemon

    if SootheDaemon.stop_running():
        typer.echo("Soothe daemon stopped.")
    else:
        typer.echo("No Soothe daemon is running.")


@server_app.command("status")
def server_status() -> None:
    """Show Soothe daemon status."""
    from soothe.cli.daemon import SootheDaemon, pid_path

    if SootheDaemon.is_running():
        pf = pid_path()
        pid = pf.read_text().strip() if pf.exists() else "?"
        typer.echo(f"Soothe daemon is running (PID: {pid})")
    else:
        typer.echo("Soothe daemon is not running.")


# ---------------------------------------------------------------------------
# soothe thread
# ---------------------------------------------------------------------------

thread_app = typer.Typer(name="thread", help="Thread lifecycle management.")
app.add_typer(thread_app)


@thread_app.command("list")
def thread_list(
    config: Annotated[
        str | None,
        typer.Option("--config", "-c", help="Path to configuration file."),
    ] = None,
    status: Annotated[
        str | None,
        typer.Option("--status", "-s", help="Filter by status (active, archived)."),
    ] = None,
) -> None:
    """List all agent threads."""
    from soothe.cli.daemon import SootheDaemon

    cfg = _load_config(config)

    # Check if daemon is running - connect to it to avoid RocksDB lock conflicts
    if SootheDaemon.is_running():
        _thread_list_via_daemon(cfg, status_filter=status)
    else:
        _thread_list_standalone(cfg, status_filter=status)


def _thread_list_via_daemon(_cfg: SootheConfig, *, status_filter: str | None = None) -> None:
    """List threads by connecting to a running daemon."""
    import asyncio

    from soothe.cli.daemon import DaemonClient

    async def _list() -> None:
        client = DaemonClient()
        try:
            await client.connect()
            await client.send_command("/thread list")
            # Read command response
            while True:
                event = await client.read_event()
                if not event:
                    break
                event_type = event.get("type", "")
                if event_type == "command_response":
                    content = event.get("content", "")
                    if content.strip():
                        # Filter by status if needed
                        if status_filter:
                            lines = content.split("\n")
                            for line in lines:
                                if status_filter in line or "ID" in line or "──" in line:
                                    typer.echo(line)
                        else:
                            typer.echo(content.strip())
                    break  # Always break after command_response, even if empty
                if event_type == "status":
                    state = event.get("state", "")
                    if state in ("idle", "stopped"):
                        break
        finally:
            await client.close()

    asyncio.run(_list())


def _thread_list_standalone(cfg: SootheConfig, *, status_filter: str | None = None) -> None:
    """List threads in standalone mode (no daemon)."""
    import asyncio

    from soothe.core.runner import SootheRunner

    runner = SootheRunner(cfg)

    async def _list() -> None:
        threads = await runner.list_threads()
        if status_filter:
            threads = [t for t in threads if t.get("status") == status_filter]
        if not threads:
            typer.echo("No threads.")
            return
        for t in threads:
            tid = t.get("thread_id", "?")
            t_status = t.get("status", "?")
            created = str(t.get("created_at", "?"))[:19]
            typer.echo(f"  {tid}  {t_status}  {created}")

    asyncio.run(_list())


@thread_app.command("resume")
def thread_resume(
    thread_id: Annotated[str, typer.Argument(help="Thread ID to resume.")],
    config: Annotated[
        str | None,
        typer.Option("--config", "-c", help="Path to configuration file."),
    ] = None,
) -> None:
    """Resume a thread in the next soothe run."""
    cfg = _load_config(config)
    _run_tui(cfg, thread_id=thread_id, config_path=config)


@thread_app.command("archive")
def thread_archive(
    thread_id: Annotated[str, typer.Argument(help="Thread ID to archive.")],
    config: Annotated[
        str | None,
        typer.Option("--config", "-c", help="Path to configuration file."),
    ] = None,
) -> None:
    """Archive a thread."""
    import asyncio

    from soothe.core.runner import SootheRunner

    cfg = _load_config(config)
    runner = SootheRunner(cfg)

    async def _archive() -> None:
        await runner._durability.archive_thread(thread_id)
        typer.echo(f"Archived thread {thread_id}.")

    asyncio.run(_archive())


@thread_app.command("inspect")
def thread_inspect(
    thread_id: Annotated[str, typer.Argument(help="Thread ID to inspect.")],
    config: Annotated[
        str | None,
        typer.Option("--config", "-c", help="Path to configuration file."),
    ] = None,
) -> None:
    """Inspect thread details."""
    import asyncio

    from soothe.cli.thread_logger import ThreadLogger
    from soothe.core.runner import SootheRunner

    cfg = _load_config(config)
    runner = SootheRunner(cfg)

    async def _inspect() -> None:
        threads = await runner.list_threads()
        match = [t for t in threads if t.get("thread_id") == thread_id]
        if not match:
            typer.echo(f"Thread {thread_id} not found.")
            return
        t = match[0]
        typer.echo(f"Thread ID:    {t.get('thread_id')}")
        typer.echo(f"Status:       {t.get('status')}")
        typer.echo(f"Created:      {t.get('created_at')}")

        logger = ThreadLogger(thread_id=thread_id)
        records = logger.read_recent_records(limit=200)
        conversations = [r for r in records if r.get("kind") == "conversation"]
        events = [r for r in records if r.get("kind") == "event"]
        typer.echo(f"Messages:     {len(conversations)}")
        typer.echo(f"Events:       {len(events)}")
        if conversations:
            last = conversations[-1]
            role = last.get("role", "?")
            text = str(last.get("text", ""))[:120]
            typer.echo(f"Last message: [{role}] {text}")

    asyncio.run(_inspect())


@thread_app.command("delete")
def thread_delete(
    thread_id: Annotated[str, typer.Argument(help="Thread ID to delete.")],
    config: Annotated[
        str | None,
        typer.Option("--config", "-c", help="Path to configuration file."),
    ] = None,
    *,
    yes: Annotated[
        bool,
        typer.Option("--yes", "-y", help="Skip confirmation."),
    ] = False,
) -> None:
    """Permanently delete a thread."""
    import asyncio

    from soothe.core.runner import SootheRunner

    if not yes:
        confirm = typer.confirm(f"Permanently delete thread {thread_id}?")
        if not confirm:
            typer.echo("Cancelled.")
            return

    cfg = _load_config(config)
    runner = SootheRunner(cfg)

    async def _delete() -> None:
        with contextlib.suppress(Exception):
            await runner._durability.archive_thread(thread_id)
        thread_file = anyio.Path(SOOTHE_HOME).expanduser() / "threads" / f"{thread_id}.jsonl"
        if await thread_file.exists():
            await thread_file.unlink()
        typer.echo(f"Deleted thread {thread_id}.")

    asyncio.run(_delete())


@thread_app.command("export")
def thread_export(
    thread_id: Annotated[str, typer.Argument(help="Thread ID to export.")],
    output: Annotated[
        str | None,
        typer.Option("--output", "-o", help="Output file path."),
    ] = None,
    export_format: Annotated[
        str,
        typer.Option("--format", "-f", help="Export format: jsonl or md."),
    ] = "jsonl",
) -> None:
    """Export thread conversation to a file."""
    from soothe.cli.thread_logger import ThreadLogger

    logger = ThreadLogger(thread_id=thread_id)
    records = logger.read_recent_records(limit=10000)

    if not records:
        typer.echo(f"No records found for thread {thread_id}.")
        return

    out_path = Path(output or f"{thread_id}.{export_format}")

    if export_format == "jsonl":
        with out_path.open("w", encoding="utf-8") as f:
            f.writelines(json.dumps(r, default=str) + "\n" for r in records)
    elif export_format == "md":
        conversations = [r for r in records if r.get("kind") == "conversation"]
        with out_path.open("w", encoding="utf-8") as f:
            f.write(f"# Thread {thread_id}\n\n")
            for c in conversations:
                role = c.get("role", "unknown").title()
                text = c.get("text", "")
                f.write(f"## {role}\n\n{text}\n\n")
    else:
        typer.echo(f"Unknown format: {export_format}. Use 'jsonl' or 'md'.", err=True)
        sys.exit(1)

    typer.echo(f"Exported to {out_path}")


# ---------------------------------------------------------------------------
# Existing commands (preserved)
# ---------------------------------------------------------------------------


@app.command()
def list_subagents_status() -> None:
    """List all available subagents and their status."""
    try:
        cfg = SootheConfig()
        from soothe.core.resolver import SUBAGENT_FACTORIES as _SUBAGENT_FACTORIES

        typer.echo("\nAvailable Subagents:")
        typer.echo("-" * 50)
        for name, sub_cfg in cfg.subagents.items():
            status = "enabled" if sub_cfg.enabled else "disabled"
            model = sub_cfg.model or cfg.resolve_model("default")
            typer.echo(f"  {name}: {status}")
            typer.echo(f"    Model: {model}")
        typer.echo("-" * 50)
        typer.echo(f"\nTotal configured: {len([s for s in cfg.subagents.values() if s.enabled])} active")
        typer.echo(f"Total available: {len(_SUBAGENT_FACTORIES)}")
    except Exception as e:
        typer.echo(f"Error: {e}", err=True)
        sys.exit(1)


@app.command("config")
def show_config(
    *,
    show_sensitive: Annotated[
        bool,
        typer.Option("--show-sensitive", "-s", help="Show sensitive values like API keys."),
    ] = False,
) -> None:
    """Display current configuration."""
    try:
        cfg = SootheConfig()

        typer.echo("\nSoothe Configuration:")
        typer.echo("=" * 50)

        typer.echo("\n[Model Router]")
        typer.echo(f"  default: {cfg.router.default}")
        for role in ("think", "fast", "image", "embedding", "web_search"):
            value = getattr(cfg.router, role, None)
            if value:
                typer.echo(f"  {role}: {value}")

        typer.echo("\n[Providers]")
        if cfg.providers:
            for p in cfg.providers:
                key_display = "[REDACTED]" if p.api_key and not show_sensitive else (p.api_key or "(not set)")
                typer.echo(
                    f"  {p.name}: type={p.provider_type}, url={p.api_base_url or '(default)'}, key={key_display}"
                )
        else:
            typer.echo("  (none)")

        typer.echo(f"  debug: {cfg.debug}")

        typer.echo("\n[Tools]")
        if cfg.tools:
            for tool in cfg.tools:
                typer.echo(f"  - {tool}")
        else:
            typer.echo("  (none)")

        typer.echo("\n[Subagents]")
        for name, sub_cfg in cfg.subagents.items():
            status = "enabled" if sub_cfg.enabled else "disabled"
            typer.echo(f"  {name}: {status}")

        typer.echo("\n[MCP Servers]")
        if cfg.mcp_servers:
            for i, server in enumerate(cfg.mcp_servers, 1):
                if server.command:
                    typer.echo(f"  {i}. {server.command} {' '.join(server.args)}")
                elif server.url:
                    typer.echo(f"  {i}. HTTP: {server.url}")
        else:
            typer.echo("  (none)")

        typer.echo("\n[Protocols]")
        typer.echo(f"  context_backend: {cfg.protocols.context.backend}")
        typer.echo(f"  memory_backend: {cfg.protocols.memory.backend}")
        typer.echo(f"  planner_routing: {cfg.protocols.planner.routing}")
        typer.echo(f"  vector_store_provider: {cfg.vector_store_provider}")

        typer.echo("\n" + "=" * 50)

    except Exception as e:
        typer.echo(f"Error: {e}", err=True)
        sys.exit(1)


if __name__ == "__main__":
    app()
