"""Thread commands for Soothe CLI (read-only diagnostics).

All thread operations communicate exclusively via daemon WebSocket RPC.
The daemon must be running for thread commands to work.

Note: Thread commands are read-only diagnostics per RFC-503 (Loop-First UX).
Users manage loops (primary entity), not threads (internal execution contexts).
For thread lifecycle management, use loop commands: soothe loop <subcommand>
"""

import asyncio
import json
import sys
from pathlib import Path
from typing import Annotated, Any

import typer
from soothe_sdk.client import WebSocketClient, is_daemon_live, websocket_url_from_config

from soothe_cli.shared import load_config

# Display limits for thread list
_TOPIC_DISPLAY_LIMIT = 30  # Max chars for last human message
_TOPIC_TRUNCATE_KEEP = 27  # Leave room for "..."
_THREAD_ID_DISPLAY_WIDTH = 20  # Max width for thread IDs
_THREAD_ID_TRUNCATE_KEEP = 17  # Leave room for "..."


def _require_daemon(ws_url: str) -> None:
    """Check daemon is running, exit with error if not."""
    live = asyncio.run(_check_daemon(ws_url))
    if not live:
        typer.echo(
            "Error: Daemon not running. Start with 'soothe daemon start'.",
            err=True,
        )
        sys.exit(1)


async def _check_daemon(ws_url: str) -> bool:
    return await is_daemon_live(ws_url, timeout=5.0)


async def _rpc(
    ws_url: str,
    send_fn: str,
    send_args: dict[str, Any],
    response_type: str,
    timeout: float = 30.0,
) -> dict[str, Any]:
    """Send an RPC request and wait for a matching response.

    Args:
        ws_url: WebSocket URL.
        send_fn: Name of the WebSocketClient method to call.
        send_args: Keyword arguments for the send method.
        response_type: Expected response message type.
        timeout: Maximum seconds to wait.

    Returns:
        Response dict from daemon.
    """
    client = WebSocketClient(url=ws_url)
    try:
        await client.connect()
        method = getattr(client, send_fn)
        await method(**send_args)
        async with asyncio.timeout(timeout):
            while True:
                event = await client.read_event()
                if not event:
                    return {"error": "Connection closed"}
                if event.get("type") == response_type:
                    return event
    except TimeoutError:
        return {"error": "Timed out waiting for daemon response"}
    finally:
        await client.close()


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
    """List all agent threads (read-only diagnostics).

    Examples:
        soothe thread list
        soothe thread list --status active
        soothe thread list --limit 10
        soothe thread list --limit 20 --status idle

    Note: For thread lifecycle management, use loop commands (RFC-503).
    """
    cfg = load_config(config)
    ws_url = websocket_url_from_config(cfg)
    _require_daemon(ws_url)

    async def _list() -> None:
        client = WebSocketClient(url=ws_url)
        try:
            await client.connect()
            filter_payload: dict[str, str] | None = None
            if status and status.lower() != "active":
                sf = status.lower()
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
                        and _thread_status_matches_cli_filter(t.get("status"), status)
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


def thread_show(
    thread_id: Annotated[str, typer.Argument(help="Thread ID to show.")],
    config: Annotated[
        str | None,
        typer.Option("--config", "-c", help="Path to configuration file."),
    ] = None,
) -> None:
    """Show thread details (read-only diagnostics).

    Example:
        soothe thread show abc123

    Note: For thread lifecycle management, use loop commands (RFC-503).
    """
    cfg = load_config(config)
    ws_url = websocket_url_from_config(cfg)
    _require_daemon(ws_url)

    async def _show() -> None:
        client = WebSocketClient(url=ws_url)
        try:
            await client.connect()

            # Get thread metadata
            await client.send_thread_get(thread_id)
            async with asyncio.timeout(30.0):
                while True:
                    event = await client.read_event()
                    if not event:
                        typer.echo("No response from daemon.", err=True)
                        return
                    etype = event.get("type", "")
                    if etype == "thread_get_response":
                        thread = event.get("thread", {})
                        typer.echo(f"Thread ID:    {thread.get('thread_id', thread_id)}")
                        typer.echo(f"Status:       {thread.get('status', 'unknown')}")
                        typer.echo(f"Created:      {thread.get('created_at', 'unknown')}")
                        typer.echo(f"Updated:      {thread.get('updated_at', 'unknown')}")
                        metadata = thread.get("metadata", {})
                        if metadata.get("tags"):
                            typer.echo(f"Tags:         {', '.join(metadata['tags'])}")
                        return
                    if etype == "error":
                        typer.echo(f"Error: {event.get('message', 'unknown')}", err=True)
                        return
        except TimeoutError:
            typer.echo("Timed out waiting for response.", err=True)
        finally:
            await client.close()

    asyncio.run(_show())


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
    """Export thread conversation to a file (read-only diagnostics).

    Example:
        soothe thread export abc123 --output out.jsonl
        soothe thread export abc123 --format md --output out.md

    Note: For thread lifecycle management, use loop commands (RFC-503).
    """
    cfg = load_config(config=None)
    ws_url = websocket_url_from_config(cfg)
    _require_daemon(ws_url)

    async def _export() -> None:
        client = WebSocketClient(url=ws_url)
        try:
            await client.connect()
            await client.send_thread_messages(thread_id, limit=10000)
            async with asyncio.timeout(60.0):
                while True:
                    event = await client.read_event()
                    if not event:
                        typer.echo("No response from daemon.", err=True)
                        return
                    if event.get("type") != "thread_messages_response":
                        continue
                    messages = event.get("messages", [])
                    if not messages:
                        typer.echo(f"No messages found for thread {thread_id}.")
                        return

                    if export_format == "md":
                        lines = [f"# Thread {thread_id}\n"]
                        for msg in messages:
                            role = msg.get("type", msg.get("role", "unknown"))
                            content = msg.get("content", "")
                            if isinstance(content, list):
                                content = "\n".join(
                                    str(c.get("text", c)) if isinstance(c, dict) else str(c)
                                    for c in content
                                )
                            lines.append(f"\n## {role}\n\n{content}\n")
                        text = "\n".join(lines)
                    else:
                        text = "\n".join(json.dumps(msg) for msg in messages) + "\n"

                    if output:
                        Path(output).write_text(text, encoding="utf-8")
                        typer.echo(f"Exported {len(messages)} messages to {output}")
                    else:
                        typer.echo(text)
                    return
        except TimeoutError:
            typer.echo("Timed out waiting for messages.", err=True)
        finally:
            await client.close()

    asyncio.run(_export())


def thread_stats(
    thread_id: Annotated[str, typer.Argument(help="Thread ID.")],
    config: Annotated[
        str | None,
        typer.Option("--config", "-c", help="Path to configuration file."),
    ] = None,
) -> None:
    """Show thread execution statistics (read-only diagnostics).

    Example:
        soothe thread stats abc123

    Note: For thread lifecycle management, use loop commands (RFC-503).
    """
    cfg = load_config(config)
    ws_url = websocket_url_from_config(cfg)
    _require_daemon(ws_url)

    async def _stats() -> None:
        client = WebSocketClient(url=ws_url)
        try:
            await client.connect()
            # Use thread_get with stats included via thread_list
            await client.send_thread_list(
                {"thread_id": thread_id}, include_stats=True, include_last_message=True
            )
            async with asyncio.timeout(30.0):
                while True:
                    event = await client.read_event()
                    if not event:
                        typer.echo("No response from daemon.", err=True)
                        return
                    if event.get("type") != "thread_list_response":
                        continue
                    threads = event.get("threads", [])
                    match = [t for t in threads if t.get("thread_id") == thread_id]
                    if not match:
                        typer.echo(f"Thread {thread_id} not found.")
                        return
                    t = match[0]
                    typer.echo(f"Thread:    {thread_id}")
                    typer.echo(f"Status:    {t.get('status', 'unknown')}")
                    typer.echo(f"Created:   {t.get('created_at', 'unknown')}")
                    typer.echo(f"Updated:   {t.get('updated_at', 'unknown')}")
                    stats = t.get("stats", {})
                    if stats:
                        typer.echo(f"Messages:  {stats.get('message_count', 'N/A')}")
                        typer.echo(f"Events:    {stats.get('event_count', 'N/A')}")
                        typer.echo(f"Artifacts: {stats.get('artifact_count', 'N/A')}")
                        typer.echo(f"Errors:    {stats.get('error_count', 'N/A')}")
                    return
        except TimeoutError:
            typer.echo("Timed out waiting for response.", err=True)
        finally:
            await client.close()

    asyncio.run(_stats())


def thread_artifacts(
    thread_id: Annotated[str, typer.Argument(help="Thread ID to list artifacts for.")],
    config: Annotated[
        str | None,
        typer.Option("--config", "-c", help="Path to configuration file."),
    ] = None,
) -> None:
    """List artifacts for a thread (read-only diagnostics).

    Example:
        soothe thread artifacts abc123

    Note: For thread lifecycle management, use loop commands (RFC-503).
    """
    cfg = load_config(config)
    ws_url = websocket_url_from_config(cfg)
    _require_daemon(ws_url)

    resp = asyncio.run(
        _rpc(ws_url, "send_thread_artifacts", {"thread_id": thread_id}, "thread_artifacts_response")
    )
    artifacts = resp.get("artifacts", [])
    if not artifacts:
        typer.echo("No artifacts found.")
        return
    typer.echo(f"{'Name':<30}  {'Type':<15}  {'Summary':<40}")
    typer.echo("─" * 90)
    for a in artifacts:
        name = str(a.get("name", ""))[:30]
        a_type = str(a.get("type", ""))[:15]
        summary = str(a.get("summary", ""))[:40]
        typer.echo(f"{name:<30}  {a_type:<15}  {summary:<40}")
