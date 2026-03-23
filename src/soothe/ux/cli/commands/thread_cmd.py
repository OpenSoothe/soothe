"""Thread commands for Soothe CLI."""

import asyncio
import contextlib
import json
import shutil
import sys
from pathlib import Path
from typing import Annotated

import typer

from soothe.config import SootheConfig


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
    from soothe.daemon import SootheDaemon
    from soothe.ux.core import load_config

    cfg = load_config(config)

    # Check if daemon is running - connect to it to avoid RocksDB lock conflicts
    if SootheDaemon.is_running():
        _thread_list_via_daemon(cfg, status_filter=status)
    else:
        _thread_list_standalone(cfg, status_filter=status)


def _thread_list_via_daemon(_cfg: SootheConfig, *, status_filter: str | None = None) -> None:
    """List threads by connecting to a running daemon."""
    from soothe.daemon import DaemonClient

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
    from soothe.core.runner import SootheRunner

    runner = SootheRunner(cfg)

    async def _list() -> None:
        threads = await runner.list_threads()
        if status_filter:
            threads = [t for t in threads if t.get("status") == status_filter]
        if not threads:
            typer.echo("No threads.")
            return
        # Print header
        typer.echo(f"{'ID':<10}  {'Status':<10}  {'Created':<19}  {'Last Message':<19}")
        typer.echo("─" * 65)
        for t in threads:
            tid = t.get("thread_id", "?")
            t_status = t.get("status", "?")
            created = str(t.get("created_at", "?"))[:19]
            last_msg = str(t.get("updated_at", "?"))[:19]
            typer.echo(f"{tid:<10}  {t_status:<10}  {created:<19}  {last_msg:<19}")

    asyncio.run(_list())


def thread_continue(
    thread_id: Annotated[
        str | None,
        typer.Argument(help="Thread ID to continue. Omit to continue last active thread."),
    ] = None,
    config: Annotated[
        str | None,
        typer.Option("--config", "-c", help="Path to configuration file."),
    ] = None,
    *,
    daemon: Annotated[
        bool,
        typer.Option("--daemon", help="Attach to running daemon instead of standalone."),
    ] = False,
    new: Annotated[
        bool,
        typer.Option("--new", help="Create a new thread instead of continuing."),
    ] = False,
) -> None:
    """Continue a conversation thread in the TUI.

    Works in two modes:
    1. Standalone (default): Runs agent directly
    2. Daemon mode (--daemon): Connects to running daemon

    Examples:
        soothe thread continue abc123          # Continue thread standalone
        soothe thread continue --daemon abc123 # Continue via daemon
        soothe thread continue --new           # Start new thread
        soothe thread continue                 # Continue last active thread
    """
    from soothe.daemon import SootheDaemon
    from soothe.ux.cli.execution import run_tui
    from soothe.ux.core import load_config

    cfg = load_config(config)

    # Handle --new flag
    if new:
        thread_id = None
    elif not thread_id:
        # Find last active thread
        from soothe.core.runner import SootheRunner

        runner = SootheRunner(cfg)

        async def get_last_thread() -> str | None:
            threads = await runner.list_threads()
            active_threads = [t for t in threads if t.get("status") in ("active", "idle")]
            if not active_threads:
                typer.echo("No active threads found.", err=True)
                sys.exit(1)
            active_threads.sort(key=lambda x: x.get("updated_at", ""), reverse=True)
            return active_threads[0].get("thread_id")

        thread_id = asyncio.run(get_last_thread())

    # Handle --daemon flag
    if daemon:
        if not SootheDaemon.is_running():
            typer.echo("Error: No daemon running. Start with 'soothe server start'.", err=True)
            sys.exit(1)

        # Connect to daemon and resume thread
        # This will trigger TUI to connect to daemon
        run_tui(cfg, thread_id=thread_id, config_path=config, daemon_mode=True)
    else:
        # Standalone mode (existing behavior)
        run_tui(cfg, thread_id=thread_id, config_path=config, daemon_mode=False)


def thread_archive(
    thread_id: Annotated[str, typer.Argument(help="Thread ID to archive.")],
    config: Annotated[
        str | None,
        typer.Option("--config", "-c", help="Path to configuration file."),
    ] = None,
) -> None:
    """Archive a thread."""
    from soothe.core.runner import SootheRunner
    from soothe.ux.core import load_config

    cfg = load_config(config)
    runner = SootheRunner(cfg)

    async def _archive() -> None:
        await runner._durability.archive_thread(thread_id)
        typer.echo(f"Archived thread {thread_id}.")

    asyncio.run(_archive())


def thread_show(
    thread_id: Annotated[str, typer.Argument(help="Thread ID to show.")],
    config: Annotated[
        str | None,
        typer.Option("--config", "-c", help="Path to configuration file."),
    ] = None,
) -> None:
    """Show thread details."""
    from soothe.core.runner import SootheRunner
    from soothe.daemon.thread_logger import ThreadLogger
    from soothe.ux.core import load_config

    cfg = load_config(config)
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
    from soothe.config import SOOTHE_HOME
    from soothe.core.runner import SootheRunner
    from soothe.ux.core import load_config

    if not yes:
        confirm = typer.confirm(f"Permanently delete thread {thread_id}?")
        if not confirm:
            typer.echo("Cancelled.")
            return

    cfg = load_config(config)
    runner = SootheRunner(cfg)

    async def _delete() -> None:
        with contextlib.suppress(Exception):
            await runner._durability.archive_thread(thread_id)
        run_dir = await asyncio.to_thread(lambda: Path(SOOTHE_HOME).expanduser() / "runs" / thread_id)
        exists = await asyncio.to_thread(run_dir.exists)
        if exists:
            await asyncio.to_thread(shutil.rmtree, run_dir)
        typer.echo(f"Deleted thread {thread_id}.")

    asyncio.run(_delete())


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
    from soothe.daemon.thread_logger import ThreadLogger

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


def thread_stats(
    thread_id: Annotated[str, typer.Argument(help="Thread ID.")],
    config: Annotated[
        str | None,
        typer.Option("--config", "-c", help="Path to configuration file."),
    ] = None,
) -> None:
    """Show thread execution statistics.

    Example:
        soothe thread stats abc123
    """
    from soothe.core.runner import SootheRunner
    from soothe.core.thread import ThreadContextManager
    from soothe.ux.core import load_config

    cfg = load_config(config)
    runner = SootheRunner(cfg)

    async def _show_stats() -> None:
        manager = ThreadContextManager(runner._durability, cfg)
        stats = await manager.get_thread_stats(thread_id)

        typer.echo(f"Thread: {thread_id}")
        typer.echo(f"Messages: {stats.message_count}")
        typer.echo(f"Events: {stats.event_count}")
        typer.echo(f"Artifacts: {stats.artifact_count}")
        typer.echo(f"Errors: {stats.error_count}")
        if stats.last_error:
            typer.echo(f"Last Error: {stats.last_error}")

    asyncio.run(_show_stats())


def thread_tag(
    thread_id: Annotated[str, typer.Argument(help="Thread ID.")],
    tags: Annotated[
        list[str],
        typer.Argument(help="Tags to add/remove."),
    ],
    config: Annotated[
        str | None,
        typer.Option("--config", "-c", help="Path to configuration file."),
    ] = None,
    *,
    remove: Annotated[
        bool,
        typer.Option("--remove", help="Remove tags instead of adding."),
    ] = False,
) -> None:
    """Add or remove tags from a thread.

    Examples:
        soothe thread tag abc123 research analysis
        soothe thread tag abc123 research --remove
    """
    from soothe.core.runner import SootheRunner
    from soothe.core.thread import ThreadContextManager
    from soothe.ux.core import load_config

    cfg = load_config(config)
    runner = SootheRunner(cfg)

    async def _tag() -> None:
        manager = ThreadContextManager(runner._durability, cfg)
        thread = await manager.get_thread(thread_id)

        # Get current metadata
        metadata = thread.metadata.copy()
        current_tags = set(metadata.get("tags", []))

        if remove:
            current_tags -= set(tags)
        else:
            current_tags |= set(tags)

        metadata["tags"] = list(current_tags)

        # Update metadata via durability protocol
        await runner._durability.update_thread_metadata(thread_id, metadata)

        typer.echo(f"Tags: {', '.join(metadata['tags'])}")

    asyncio.run(_tag())
