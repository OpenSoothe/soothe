"""Main CLI entry point using Typer."""

import json
import shutil
import sys
from pathlib import Path
from typing import Annotated

import typer

from soothe.config import SOOTHE_HOME, SootheConfig

app = typer.Typer(
    name="soothe",
    help="Multi-agent harness built on deepagents and langchain/langgraph.",
    add_completion=False,
)

_DEFAULT_CONFIG_PATH = Path(SOOTHE_HOME) / "config" / "config.yml"


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

        from soothe.cli.commands import SUBAGENT_DISPLAY_NAMES, BUILTIN_SUBAGENT_NAMES

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
    """Load SootheConfig from a file path or defaults.

    When no ``config_path`` is provided, automatically checks
    ``~/.soothe/config/config.yml`` and loads it if present.

    Args:
        config_path: Path to a YAML/JSON config file, or ``None`` for defaults.

    Returns:
        A ``SootheConfig`` instance.
    """
    if not config_path and _DEFAULT_CONFIG_PATH.is_file():
        config_path = str(_DEFAULT_CONFIG_PATH)

    if not config_path:
        return SootheConfig()

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

    return SootheConfig(**config_data)


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
    no_tui: Annotated[
        bool,
        typer.Option("--no-tui", help="Disable TUI; run single prompt and exit."),
    ] = False,
    output_format: Annotated[
        str,
        typer.Option("--format", "-f", help="Output format for headless mode: text or jsonl."),
    ] = "text",
) -> None:
    """Run the Soothe agent with a prompt or in interactive TUI mode."""
    try:
        cfg = _load_config(config)

        if prompt or no_tui:
            _run_headless(cfg, prompt or "", thread_id=thread, output_format=output_format)
        else:
            _run_tui(cfg, thread_id=thread)

    except KeyboardInterrupt:
        typer.echo("\nInterrupted.")
        sys.exit(0)
    except Exception as e:
        typer.echo(f"Error: {e}", err=True)
        sys.exit(1)


def _run_tui(cfg: SootheConfig, *, thread_id: str | None = None) -> None:
    """Launch the Textual TUI (with daemon auto-start)."""
    try:
        from soothe.cli.tui_app import run_textual_tui

        run_textual_tui(config=cfg, thread_id=thread_id)
    except ImportError:
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
    output_format: str = "text",
) -> None:
    """Run a single prompt with streaming output and progress events."""
    import asyncio

    from soothe.cli.runner import SootheRunner

    runner = SootheRunner(cfg)

    _chunk_len = 3
    _msg_pair_len = 2
    exit_code = 0

    async def _stream() -> int:
        nonlocal exit_code
        from langchain_core.messages import AIMessage, AIMessageChunk

        full_response: list[str] = []
        seen_message_ids: set[str] = set()
        has_error = False

        async for chunk in runner.astream(prompt, thread_id=thread_id):
            if not isinstance(chunk, tuple) or len(chunk) != _chunk_len:
                continue
            namespace, mode, data = chunk

            if output_format == "jsonl":
                sys.stdout.write(
                    json.dumps({"namespace": list(namespace), "mode": mode, "data": data}, default=str) + "\n"
                )
                sys.stdout.flush()
                continue

            if mode == "custom" and isinstance(data, dict):
                etype = data.get("type", "")
                if etype.startswith("soothe."):
                    _render_progress_event(data)
                if etype == "soothe.error":
                    has_error = True

            if mode == "messages" and not namespace:
                if not isinstance(data, tuple) or len(data) != _msg_pair_len:
                    continue
                msg, metadata = data
                if metadata and metadata.get("lc_source") == "summarization":
                    continue
                if isinstance(msg, AIMessage) and hasattr(msg, "content_blocks"):
                    msg_id = msg.id or ""
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
        return 1 if has_error else 0

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
                default_models = [m for m in provider.models if m in [cfg.router.default, getattr(cfg.router, role, None)]]
                is_default = "✓" if any(p.name in cfg.router.default or p.name in (getattr(cfg.router, role, None) or "").split(":")[0] for p in [provider] if p.name == (cfg.router.default or "").split(":")[0]) else ""
                providers_table.add_row(provider.name, f"{model_count} models", "✓" if cfg.router.default.startswith(f"{provider.name}:") else "")

            if not cfg.providers:
                providers_table.add_row("None configured", "", "")

            # Subagents summary
            from soothe.cli.commands import SUBAGENT_DISPLAY_NAMES, BUILTIN_SUBAGENT_NAMES

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
            general_table.add_row("Context Backend", cfg.context_backend.title())
            general_table.add_row("Memory Backend", cfg.memory_backend.title())
            general_table.add_row("Policy Profile", cfg.policy_profile)
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


def _render_progress_event(data: dict) -> None:
    """Render a soothe.* event as a structured progress line to stderr."""
    etype = data.get("type", "")
    tag = etype.replace("soothe.", "").split(".")[0] if "." in etype else "soothe"
    parts: list[str] = []

    if etype == "soothe.context.projected":
        parts = [f"{data.get('entries', 0)} entries, {data.get('tokens', 0)} tokens"]
    elif etype == "soothe.memory.recalled":
        parts = [f"{data.get('count', 0)} items recalled"]
    elif etype == "soothe.plan.created":
        steps = data.get("steps", [])
        parts = [f"{len(steps)} steps created"]
    elif etype == "soothe.policy.checked":
        parts = [data.get("verdict", "?")]
    elif etype == "soothe.session.started" or etype == "soothe.session.ended":
        parts = [f"thread={data.get('thread_id', '?')}"]
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
) -> None:
    """Attach the TUI to an already-running Soothe daemon."""
    from soothe.cli.daemon import SootheDaemon

    if not SootheDaemon.is_running():
        typer.echo("Error: No Soothe daemon is running. Use 'soothe run' or 'soothe server start'.", err=True)
        sys.exit(1)

    cfg = _load_config(config)
    try:
        from soothe.cli.tui_app import run_textual_tui

        run_textual_tui(config=cfg)
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

    template = Path(__file__).resolve().parent.parent.parent.parent / "config" / "soothe_home_config.yml"
    if not template.exists():
        template = Path(__file__).resolve().parent.parent.parent.parent / "config" / "config.yml"

    target.parent.mkdir(parents=True, exist_ok=True)
    if template.exists():
        shutil.copy2(template, target)
        typer.echo(f"Created {target}")
    else:
        target.write_text("# Soothe configuration\n# See docs/user_guide.md for options\n")
        typer.echo(f"Created minimal {target}")

    for subdir in ("sessions", "generated_agents", "logs"):
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
    foreground: Annotated[
        bool,
        typer.Option("--foreground", help="Run in foreground (don't daemonize)."),
    ] = False,
) -> None:
    """Start the Soothe daemon."""
    from soothe.cli.daemon import SootheDaemon, run_daemon

    if SootheDaemon.is_running():
        typer.echo("Soothe daemon is already running.")
        return

    cfg = _load_config(config)

    if foreground:
        run_daemon(cfg)
    else:
        import subprocess

        cmd = [sys.executable, "-m", "soothe.cli.daemon"]
        if config:
            cmd.extend(["--config", config])
        subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
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
    import asyncio

    from soothe.cli.runner import SootheRunner

    cfg = _load_config(config)
    runner = SootheRunner(cfg)

    async def _list() -> None:
        threads = await runner.list_threads()
        if status:
            threads = [t for t in threads if t.get("status") == status]
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
    _run_tui(cfg, thread_id=thread_id)


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

    from soothe.cli.runner import SootheRunner
    from soothe.cli.session import SessionLogger

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

        logger = SessionLogger(thread_id=thread_id)
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
    yes: Annotated[
        bool,
        typer.Option("--yes", "-y", help="Skip confirmation."),
    ] = False,
) -> None:
    """Permanently delete a thread."""
    import asyncio

    from soothe.cli.runner import SootheRunner

    if not yes:
        confirm = typer.confirm(f"Permanently delete thread {thread_id}?")
        if not confirm:
            typer.echo("Cancelled.")
            return

    cfg = _load_config(config)
    runner = SootheRunner(cfg)

    async def _delete() -> None:
        try:
            await runner._durability.archive_thread(thread_id)
        except Exception:
            pass
        session_file = Path(SOOTHE_HOME).expanduser() / "sessions" / f"{thread_id}.jsonl"
        if session_file.exists():
            session_file.unlink()
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
    from soothe.cli.session import SessionLogger

    logger = SessionLogger(thread_id=thread_id)
    records = logger.read_recent_records(limit=10000)

    if not records:
        typer.echo(f"No records found for thread {thread_id}.")
        return

    out_path = output or f"{thread_id}.{export_format}"

    if export_format == "jsonl":
        with open(out_path, "w", encoding="utf-8") as f:
            f.writelines(json.dumps(r, default=str) + "\n" for r in records)
    elif export_format == "md":
        conversations = [r for r in records if r.get("kind") == "conversation"]
        with open(out_path, "w", encoding="utf-8") as f:
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
