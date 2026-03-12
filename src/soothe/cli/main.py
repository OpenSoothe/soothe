"""Main CLI entry point using Typer."""

import sys
from typing import Annotated

import typer

from soothe.config import SootheConfig

app = typer.Typer(
    name="soothe",
    help="Multi-agent harness built on deepagents and langchain/langgraph.",
    add_completion=False,
)


def _load_config(config_path: str | None) -> SootheConfig:
    """Load SootheConfig from a file path or defaults.

    Args:
        config_path: Path to a YAML/JSON config file, or ``None`` for defaults.

    Returns:
        A ``SootheConfig`` instance.
    """
    if not config_path:
        return SootheConfig()

    import json

    with open(config_path) as f:
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

    return SootheConfig(**config_data)


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
    no_tui: Annotated[
        bool,
        typer.Option("--no-tui", help="Disable TUI; run single prompt and exit."),
    ] = False,
) -> None:
    """Run the Soothe agent with a prompt or in interactive TUI mode."""
    try:
        cfg = _load_config(config)

        if prompt or no_tui:
            _run_headless(cfg, prompt or "", thread_id=thread)
        else:
            _run_tui(cfg, thread_id=thread)

    except KeyboardInterrupt:
        typer.echo("\nInterrupted.")
        sys.exit(0)
    except Exception as e:
        typer.echo(f"Error: {e}", err=True)
        sys.exit(1)


def _run_tui(cfg: SootheConfig, *, thread_id: str | None = None) -> None:
    """Launch the interactive Rich TUI."""
    from soothe.cli.runner import SootheRunner
    from soothe.cli.tui import run_agent_tui

    runner = SootheRunner(cfg)
    if thread_id:
        runner.set_current_thread_id(thread_id)
    run_agent_tui(runner)


def _run_headless(
    cfg: SootheConfig,
    prompt: str,
    *,
    thread_id: str | None = None,
) -> None:
    """Run a single prompt with streaming output."""
    import asyncio

    from soothe.cli.runner import SootheRunner

    runner = SootheRunner(cfg)

    _chunk_len = 3
    _msg_pair_len = 2

    async def _stream() -> None:
        from langchain_core.messages import AIMessage, AIMessageChunk

        full_response: list[str] = []
        seen_message_ids: set[str] = set()
        async for chunk in runner.astream(prompt, thread_id=thread_id):
            if not isinstance(chunk, tuple) or len(chunk) != _chunk_len:
                continue
            namespace, mode, data = chunk
            if mode == "messages" and not namespace:
                if not isinstance(data, tuple) or len(data) != _msg_pair_len:
                    continue
                msg, metadata = data
                if metadata and metadata.get("lc_source") == "summarization":
                    continue
                if isinstance(msg, AIMessage) and hasattr(msg, "content_blocks"):
                    msg_id = msg.id or ""
                    # Complete (non-chunk) messages duplicate the streaming chunks
                    if not isinstance(msg, AIMessageChunk):
                        if msg_id in seen_message_ids:
                            continue
                        seen_message_ids.add(msg_id)
                    elif msg_id:
                        seen_message_ids.add(msg_id)
                    for block in msg.content_blocks:
                        if isinstance(block, dict) and block.get("type") == "text":
                            text = block.get("text", "")
                            if text:
                                sys.stdout.write(text)
                                sys.stdout.flush()
                                full_response.append(text)
        if full_response:
            sys.stdout.write("\n")
            sys.stdout.flush()

    asyncio.run(_stream())


# ---------------------------------------------------------------------------
# Thread management subcommands
# ---------------------------------------------------------------------------

thread_app = typer.Typer(name="thread", help="Thread lifecycle management.")
app.add_typer(thread_app)


@thread_app.command("list")
def thread_list(
    config: Annotated[
        str | None,
        typer.Option("--config", "-c", help="Path to configuration file."),
    ] = None,
) -> None:
    """List all agent threads."""
    import asyncio

    from soothe.cli.runner import SootheRunner

    cfg = _load_config(config)
    runner = SootheRunner(cfg)

    async def _list() -> None:
        threads = await runner.list_threads()
        if not threads:
            typer.echo("No threads.")
            return
        for t in threads:
            tid = t.get("thread_id", "?")
            status = t.get("status", "?")
            created = str(t.get("created_at", "?"))[:19]
            typer.echo(f"  {tid}  {status}  {created}")

    asyncio.run(_list())


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

    from soothe.cli.runner import SootheRunner

    cfg = _load_config(config)
    runner = SootheRunner(cfg)

    async def _archive() -> None:
        await runner._durability.archive_thread(thread_id)
        typer.echo(f"Archived thread {thread_id}.")

    asyncio.run(_archive())


# ---------------------------------------------------------------------------
# Existing commands (preserved)
# ---------------------------------------------------------------------------


@app.command()
def list_subagents() -> None:
    """List all available subagents and their status."""
    try:
        cfg = SootheConfig()
        from soothe.agent import _SUBAGENT_FACTORIES

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
        typer.echo(f"  context_backend: {cfg.context_backend}")
        typer.echo(f"  memory_backend: {cfg.memory_backend}")
        typer.echo(f"  planner_routing: {cfg.planner_routing}")
        typer.echo(f"  vector_store_provider: {cfg.vector_store_provider}")

        typer.echo("\n" + "=" * 50)

    except Exception as e:
        typer.echo(f"Error: {e}", err=True)
        sys.exit(1)


if __name__ == "__main__":
    app()
