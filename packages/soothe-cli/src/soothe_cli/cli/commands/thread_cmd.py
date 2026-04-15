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

# Display limits for thread list
_TOPIC_DISPLAY_LIMIT = 30  # Max chars for last human message
_TOPIC_TRUNCATE_KEEP = 27  # Leave room for "..."
_THREAD_ID_DISPLAY_WIDTH = 20  # Max width for thread IDs
_THREAD_ID_TRUNCATE_KEEP = 17  # Leave room for "..."


def _thread_status_matches_cli_filter(thread_status: str | None, status_filter: str | None) -> bool:
    """Match CLI ``--status`` against persisted thread status strings."""
    if not status_filter:
        return True
    s = (thread_status or "").lower()
    f = status_filter.lower()
    if f == "active":
        return s in ("idle", "running", "active")
    return s == f


def _echo_thread_table(rows: list[dict[str, object]]) -> None:
    """Print thread table rows (from ``model_dump`` JSON or API dicts)."""
    if not rows:
        typer.echo("No threads.")
        return
    typer.echo(f"{'ID':<20}  {'Status':<10}  {'Created':<19}  {'Last Message':<19}  {'Topic':<30}")
    typer.echo("─" * 104)
    for raw in rows:
        tid_raw = str(raw.get("thread_id", ""))
        tid = (
            tid_raw
            if len(tid_raw) <= _THREAD_ID_DISPLAY_WIDTH
            else tid_raw[:_THREAD_ID_TRUNCATE_KEEP] + "..."
        )
        t_status = str(raw.get("status", ""))
        created = str(raw.get("created_at", ""))[:19]
        last_msg = str(raw.get("updated_at", ""))[:19]
        last_human = raw.get("last_human_message")
        topic_raw = str(last_human) if last_human is not None else ""
        topic = (
            topic_raw[:_TOPIC_TRUNCATE_KEEP] + "..."
            if len(topic_raw) > _TOPIC_DISPLAY_LIMIT
            else topic_raw
        )
        typer.echo(f"{tid:<20}  {t_status:<10}  {created:<19}  {last_msg:<19}  {topic:<30}")


def thread_list(
    config: Annotated[
        str | None,
        typer.Option("--config", "-c", help="Path to configuration file."),
    ] = None,
    status: Annotated[
        str | None,
        typer.Option("--status", "-s", help="Filter by status (active, archived)."),
    ] = None,
    limit: Annotated[
        int | None,
        typer.Option("--limit", "-l", help="Limit number of threads shown."),
    ] = None,
) -> None:
    """List all agent threads.

    Examples:
        soothe thread list
        soothe thread list --status active
        soothe thread list --limit 10
        soothe thread list --limit 20 --status idle
    """
    from soothe.daemon import SootheDaemon

    from soothe_cli.shared import load_config

    cfg = load_config(config)

    # Check if daemon is running - connect to it to avoid RocksDB lock conflicts
    if SootheDaemon.is_running():
        _thread_list_via_daemon(cfg, status_filter=status, limit=limit)
    else:
        _thread_list_direct(cfg, status_filter=status, limit=limit)


def _thread_list_via_daemon(
    cfg: SootheConfig, *, status_filter: str | None = None, limit: int | None = None
) -> None:
    """List threads by connecting to a running daemon via WebSocket.

    Uses the ``thread_list`` / ``thread_list_response`` protocol. The legacy path
    read ``command_response`` but exited on the first ``status`` event, which is
    always sent during the WebSocket handshake (idle), so the table never printed.
    """
    from soothe.daemon import WebSocketClient

    host = cfg.daemon.transports.websocket.host
    port = cfg.daemon.transports.websocket.port
    ws_url = f"ws://{host}:{port}"

    async def _list() -> None:
        client = WebSocketClient(url=ws_url)
        try:
            await client.connect()
            filter_payload: dict[str, str] | None = None
            if status_filter and status_filter.lower() != "active":
                sf = status_filter.lower()
                if sf in ("archived", "suspended", "idle", "running", "error"):
                    filter_payload = {"status": sf}

            await client.send_thread_list(filter_payload, include_last_message=True)

            async with asyncio.timeout(60.0):
                while True:
                    event = await client.read_event()
                    if not event:
                        typer.echo("No response from daemon.", err=True)
                        return
                    if event.get("type") != "thread_list_response":
                        continue
                    threads = event.get("threads", [])
                    if not isinstance(threads, list):
                        threads = []
                    filtered = [
                        t
                        for t in threads
                        if isinstance(t, dict)
                        and _thread_status_matches_cli_filter(t.get("status"), status_filter)
                    ]
                    filtered.sort(key=lambda x: str(x.get("updated_at", "")), reverse=True)
                    if limit is not None and limit > 0:
                        filtered = filtered[:limit]
                    _echo_thread_table(filtered)
                    return
        except TimeoutError:
            typer.echo("Timed out waiting for thread list from daemon.", err=True)
        finally:
            await client.close()

    asyncio.run(_list())


def _thread_list_direct(
    cfg: SootheConfig, *, status_filter: str | None = None, limit: int | None = None
) -> None:
    """List threads directly from durability backend (no daemon connection)."""
    from soothe_daemon.core.runner import SootheRunner
    from soothe_daemon.core.thread import ThreadContextManager

    runner = SootheRunner(cfg)

    async def _list() -> None:
        try:
            manager = ThreadContextManager(
                runner._durability, cfg, getattr(runner, "_context", None)
            )
            threads = await manager.list_threads(include_last_message=True)
            if status_filter:
                threads = [
                    t for t in threads if _thread_status_matches_cli_filter(t.status, status_filter)
                ]
            threads.sort(key=lambda x: x.updated_at, reverse=True)
            if limit is not None and limit > 0:
                threads = threads[:limit]
            rows = [t.model_dump(mode="json") for t in threads]
            _echo_thread_table(rows)
        finally:
            await runner.cleanup()

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
    new: Annotated[
        bool,
        typer.Option("--new", help="Create a new thread instead of continuing."),
    ] = False,
) -> None:
    """Continue a conversation thread in the TUI.

    Requires a running daemon. Start daemon with 'soothe-daemon start' first.

    Examples:
        soothe thread continue abc123
        soothe thread continue --new
        soothe thread continue
    """
    from soothe.daemon import SootheDaemon

    from soothe_cli.cli.execution import run_tui
    from soothe_cli.shared import load_config, setup_logging

    cfg = load_config(config)
    setup_logging(cfg)

    # Check if daemon is running - required for thread continuation
    if not SootheDaemon.is_running():
        typer.echo("Error: No daemon running. Start with 'soothe-daemon start'.", err=True)
        sys.exit(1)

    # Handle --new flag
    if new:
        thread_id = None
    elif not thread_id:
        # Find the most recently updated active thread through the daemon via WebSocket
        async def get_last_thread_via_daemon() -> str | None:
            """Find the most recently updated active thread through the daemon via WebSocket."""
            from soothe.daemon import WebSocketClient

            host = cfg.daemon.transports.websocket.host
            port = cfg.daemon.transports.websocket.port
            client = WebSocketClient(url=f"ws://{host}:{port}")
            try:
                await client.connect()
                await client.send_thread_list()
                while True:
                    event = await client.read_event()
                    if not event:
                        break
                    if event.get("type") != "thread_list_response":
                        continue
                    threads = event.get("threads", [])
                    active_threads = [t for t in threads if t.get("status") in ("active", "idle")]
                    if not active_threads:
                        typer.echo("No active threads found.", err=True)
                        sys.exit(1)
                    active_threads.sort(key=lambda x: x.get("updated_at", ""), reverse=True)
                    return active_threads[0].get("thread_id")
            finally:
                await client.close()

            typer.echo("No active threads found.", err=True)
            sys.exit(1)

        thread_id = asyncio.run(get_last_thread_via_daemon())

    # Connect to daemon and resume thread
    # This will trigger TUI to connect to daemon
    run_tui(cfg, thread_id=thread_id, config_path=config)


def thread_archive(
    thread_id: Annotated[str, typer.Argument(help="Thread ID to archive.")],
    config: Annotated[
        str | None,
        typer.Option("--config", "-c", help="Path to configuration file."),
    ] = None,
) -> None:
    """Archive a thread.

    Example:
        soothe thread archive abc123
    """
    from soothe_daemon.core.runner import SootheRunner

    from soothe_cli.shared import load_config

    cfg = load_config(config)
    runner = SootheRunner(cfg)

    async def _archive() -> None:
        try:
            from soothe_daemon.core.thread import ThreadContextManager

            manager = ThreadContextManager(
                runner._durability, cfg, getattr(runner, "_context", None)
            )
            await manager.archive_thread(thread_id)
            typer.echo(f"Archived thread {thread_id}.")
        finally:
            await runner.cleanup()

    asyncio.run(_archive())


def thread_show(
    thread_id: Annotated[str, typer.Argument(help="Thread ID to show.")],
    config: Annotated[
        str | None,
        typer.Option("--config", "-c", help="Path to configuration file."),
    ] = None,
) -> None:
    """Show thread details.

    Example:
        soothe thread show abc123
    """
    from soothe.logging import ThreadLogger
    from soothe_daemon.core.runner import SootheRunner

    from soothe_cli.shared import load_config

    cfg = load_config(config)
    runner = SootheRunner(cfg)

    async def _inspect() -> None:
        try:
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
        finally:
            await runner.cleanup()

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
    """Permanently delete a thread.

    Example:
        soothe thread delete abc123
    """
    from soothe_sdk import SOOTHE_HOME
    from soothe_daemon.core.runner import SootheRunner

    from soothe_cli.shared import load_config

    if not yes:
        confirm = typer.confirm(f"Permanently delete thread {thread_id}?")
        if not confirm:
            typer.echo("Cancelled.")
            return

    cfg = load_config(config)
    runner = SootheRunner(cfg)

    async def _delete() -> None:
        try:
            from soothe_daemon.core.thread import ThreadContextManager

            manager = ThreadContextManager(
                runner._durability, cfg, getattr(runner, "_context", None)
            )
            with contextlib.suppress(Exception):
                await manager.archive_thread(thread_id)
            run_dir = await asyncio.to_thread(
                lambda: Path(SOOTHE_HOME).expanduser() / "runs" / thread_id
            )
            exists = await asyncio.to_thread(run_dir.exists)
            if exists:
                await asyncio.to_thread(shutil.rmtree, run_dir)
            typer.echo(f"Deleted thread {thread_id}.")
        finally:
            await runner.cleanup()

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
    """Export thread conversation to a file.

    Example:
        soothe thread export abc123 --output out.json
    """
    from soothe.logging import ThreadLogger

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
    from soothe_daemon.core.runner import SootheRunner
    from soothe_daemon.core.thread import ThreadContextManager

    from soothe_cli.shared import load_config

    cfg = load_config(config)
    runner = SootheRunner(cfg)

    async def _show_stats() -> None:
        try:
            manager = ThreadContextManager(
                runner._durability, cfg, getattr(runner, "_context", None)
            )
            stats = await manager.get_thread_stats(thread_id)

            typer.echo(f"Thread: {thread_id}")
            typer.echo(f"Messages: {stats.message_count}")
            typer.echo(f"Events: {stats.event_count}")
            typer.echo(f"Artifacts: {stats.artifact_count}")
            typer.echo(f"Errors: {stats.error_count}")
            if stats.last_error:
                typer.echo(f"Last Error: {stats.last_error}")
        finally:
            await runner.cleanup()

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
    from soothe_daemon.core.runner import SootheRunner
    from soothe_daemon.core.thread import ThreadContextManager

    from soothe_cli.shared import load_config

    cfg = load_config(config)
    runner = SootheRunner(cfg)

    async def _tag() -> None:
        try:
            manager = ThreadContextManager(
                runner._durability, cfg, getattr(runner, "_context", None)
            )
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
        finally:
            await runner.cleanup()

    asyncio.run(_tag())
