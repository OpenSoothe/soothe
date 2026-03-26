"""Main CLI entry point using Typer."""

from importlib.metadata import version
from typing import Annotated, Literal

import typer

app = typer.Typer(
    name="soothe",
    help="Intelligent AI assistant for complex tasks",
    no_args_is_help=False,
    add_completion=False,
)


def add_help_alias(app: typer.Typer) -> None:
    """Add -h as alias for --help to a Typer app."""

    @app.callback(invoke_without_command=True)
    def callback(
        ctx: typer.Context,
        show_help: Annotated[  # noqa: FBT002
            bool,
            typer.Option("-h", "--help", is_flag=True, help="Show this message and exit."),
        ] = False,
    ) -> None:
        if show_help:
            typer.echo(ctx.get_help())
            raise typer.Exit


@app.callback(invoke_without_command=True)
def main(
    ctx: typer.Context,
    config: Annotated[
        str | None,
        typer.Option("--config", "-c", help="Path to configuration file."),
    ] = None,
    prompt: Annotated[
        str | None,
        typer.Option("--prompt", "-p", help="Prompt to send as user message (headless single-shot mode)."),
    ] = None,
    no_tui: Annotated[  # noqa: FBT002
        bool,
        typer.Option("--no-tui", help="Disable TUI; run single prompt and exit."),
    ] = False,
    output_format: Annotated[
        str,
        typer.Option("--format", "-f", help="Output format for headless mode: text or jsonl."),
    ] = "text",
    verbosity: Annotated[
        Literal["minimal", "normal", "detailed", "debug"] | None,
        typer.Option(
            "--verbosity",
            "-v",
            help="Verbosity level: minimal, normal, detailed, debug.",
        ),
    ] = None,
    show_help: Annotated[  # noqa: FBT002
        bool,
        typer.Option("--help", "-h", is_flag=True, help="Show this message and exit."),
    ] = False,
    show_version: Annotated[  # noqa: FBT002
        bool,
        typer.Option("--version", is_flag=True, help="Show version and exit."),
    ] = False,
) -> None:
    """Soothe - Intelligent AI assistant for complex tasks.

    Run without arguments for interactive TUI mode, or provide a prompt as the first argument.

    Examples:
        soothe                           # Interactive TUI mode
        soothe "Research AI advances"    # Headless single-prompt mode
        soothe --config custom.yml       # Use custom config
        soothe --no-tui -p "how are you" # Headless mode with prompt
    """
    # Handle -h/--help flag
    if show_help:
        typer.echo(ctx.get_help())
        raise typer.Exit

    # Handle --version flag
    if show_version:
        typer.echo(f"soothe {version('soothe')}")
        raise typer.Exit

    # Only run default behavior if no subcommand is being invoked
    if ctx.invoked_subcommand is None:
        # Get prompt from -p/--prompt option, or fall back to remaining args
        effective_prompt = prompt if prompt is not None else (" ".join(ctx.args) if ctx.args else None)

        from soothe.ux.cli.commands.run_cmd import run_impl

        run_impl(
            prompt=effective_prompt,
            config=config,
            thread_id=None,
            no_tui=no_tui,
            autonomous=False,
            max_iterations=None,
            output_format=output_format,
            verbosity=verbosity,
        )


# ---------------------------------------------------------------------------
# Thread Command (Nested Subcommands)
# ---------------------------------------------------------------------------

thread_app = typer.Typer(name="thread", help="Manage conversation threads")
add_help_alias(thread_app)
app.add_typer(thread_app)


@thread_app.command("list")
def _thread_list(
    config: Annotated[
        str | None,
        typer.Option("--config", "-c", help="Path to configuration file."),
    ] = None,
    status: Annotated[
        str | None,
        typer.Option("--status", "-s", help="Filter by status (active, archived)."),
    ] = None,
) -> None:
    """List all conversation threads.

    Examples:
        soothe thread list
        soothe thread list --status active
    """
    from soothe.ux.cli.commands.thread_cmd import thread_list

    thread_list(config=config, status=status)


@thread_app.command("show")
def _thread_show(
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
    from soothe.ux.cli.commands.thread_cmd import thread_show

    thread_show(thread_id=thread_id, config=config)


@thread_app.command("continue")
def _thread_continue(
    thread_id: Annotated[
        str | None,
        typer.Argument(help="Thread ID to continue. Omit to continue last active thread."),
    ] = None,
    config: Annotated[
        str | None,
        typer.Option("--config", "-c", help="Path to configuration file."),
    ] = None,
    daemon: Annotated[  # noqa: FBT002
        bool,
        typer.Option("--daemon", help="Attach to running daemon instead of standalone."),
    ] = False,
    new: Annotated[  # noqa: FBT002
        bool,
        typer.Option("--new", help="Create a new thread instead of continuing."),
    ] = False,
) -> None:
    """Continue a conversation thread in the TUI.

    Examples:
        soothe thread continue abc123
        soothe thread continue abc123 --daemon
        soothe thread continue --new
        soothe thread continue
    """
    from soothe.ux.cli.commands.thread_cmd import thread_continue

    thread_continue(thread_id=thread_id, config=config, daemon=daemon, new=new)


@thread_app.command("archive")
def _thread_archive(
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
    from soothe.ux.cli.commands.thread_cmd import thread_archive

    thread_archive(thread_id=thread_id, config=config)


@thread_app.command("delete")
def _thread_delete(
    thread_id: Annotated[str, typer.Argument(help="Thread ID to delete.")],
    config: Annotated[
        str | None,
        typer.Option("--config", "-c", help="Path to configuration file."),
    ] = None,
    yes: Annotated[  # noqa: FBT002
        bool,
        typer.Option("--yes", "-y", help="Skip confirmation."),
    ] = False,
) -> None:
    """Permanently delete a thread.

    Example:
        soothe thread delete abc123
    """
    from soothe.ux.cli.commands.thread_cmd import thread_delete

    thread_delete(thread_id=thread_id, config=config, yes=yes)


@thread_app.command("export")
def _thread_export(
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
    from soothe.ux.cli.commands.thread_cmd import thread_export

    thread_export(thread_id=thread_id, output=output, export_format=export_format)


@thread_app.command("stats")
def _thread_stats(
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
    from soothe.ux.cli.commands.thread_cmd import thread_stats

    thread_stats(thread_id=thread_id, config=config)


@thread_app.command("tag")
def _thread_tag(
    thread_id: Annotated[str, typer.Argument(help="Thread ID.")],
    tags: Annotated[
        list[str],
        typer.Argument(help="Tags to add/remove."),
    ],
    config: Annotated[
        str | None,
        typer.Option("--config", "-c", help="Path to configuration file."),
    ] = None,
    remove: Annotated[  # noqa: FBT002
        bool,
        typer.Option("--remove", help="Remove tags instead of adding."),
    ] = False,
) -> None:
    """Add or remove tags from a thread.

    Examples:
        soothe thread tag abc123 research analysis
        soothe thread tag abc123 research --remove
    """
    from soothe.ux.cli.commands.thread_cmd import thread_tag

    thread_tag(thread_id=thread_id, tags=tags, config=config, remove=remove)


# ---------------------------------------------------------------------------
# Daemon Command (Nested Subcommands)
# ---------------------------------------------------------------------------

daemon_app = typer.Typer(name="daemon", help="Manage daemon process")
add_help_alias(daemon_app)
app.add_typer(daemon_app)


@daemon_app.command("start")
def _daemon_start(
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
    from soothe.ux.cli.commands.daemon_cmd import daemon_start

    daemon_start(config=config, foreground=foreground)


@daemon_app.command("stop")
def _daemon_stop() -> None:
    """Stop the running Soothe daemon."""
    from soothe.ux.cli.commands.daemon_cmd import daemon_stop

    daemon_stop()


@daemon_app.command("status")
def _daemon_status() -> None:
    """Show Soothe daemon status."""
    from soothe.ux.cli.commands.daemon_cmd import daemon_status

    daemon_status()


@daemon_app.command("restart")
def _daemon_restart(
    config: Annotated[
        str | None,
        typer.Option("--config", "-c", help="Path to configuration file."),
    ] = None,
) -> None:
    """Restart the Soothe daemon."""
    from soothe.ux.cli.commands.daemon_cmd import daemon_restart

    daemon_restart(config=config)


# ---------------------------------------------------------------------------
# Config Command (Nested Subcommands)
# ---------------------------------------------------------------------------

config_app = typer.Typer(name="config", help="Manage Soothe configuration")
add_help_alias(config_app)
app.add_typer(config_app)


@config_app.command("show")
def _config_show(
    config: Annotated[
        str | None,
        typer.Option("--config", "-c", help="Path to configuration file."),
    ] = None,
    format_output: Annotated[
        str,
        typer.Option("--format", "-f", help="Output format: json or summary."),
    ] = "summary",
    show_sensitive: Annotated[  # noqa: FBT002
        bool,
        typer.Option("--show-sensitive", help="Show sensitive values like API keys."),
    ] = False,
) -> None:
    """Display current configuration.

    Examples:
        soothe config show
        soothe config show --show-sensitive
        soothe config show --format json
    """
    from soothe.ux.cli.commands.config_cmd import config_show

    config_show(config=config, format_output=format_output, show_sensitive=show_sensitive)


@config_app.command("init")
def _config_init(
    force: Annotated[  # noqa: FBT002
        bool,
        typer.Option("--force", "-f", help="Overwrite existing configuration without confirmation."),
    ] = False,
) -> None:
    """Initialize ~/.soothe with a default configuration.

    Examples:
        soothe config init
        soothe config init --force
    """
    from soothe.ux.cli.commands.config_cmd import config_init

    config_init(force=force)


@config_app.command("validate")
def _config_validate(
    config: Annotated[
        str | None,
        typer.Option("--config", "-c", help="Path to configuration file."),
    ] = None,
) -> None:
    """Validate configuration file and show basic info.

    Examples:
        soothe config validate
        soothe config validate --config custom.yml
    """
    from soothe.ux.cli.commands.config_cmd import config_validate

    config_validate(config=config)


# ---------------------------------------------------------------------------
# Agent Command (Nested Subcommands)
# ---------------------------------------------------------------------------

agent_app = typer.Typer(name="agent", help="List and manage agents")
add_help_alias(agent_app)
app.add_typer(agent_app)


@agent_app.command("list")
def _agent_list(
    config: Annotated[
        str | None,
        typer.Option("--config", "-c", help="Path to configuration file."),
    ] = None,
    enabled: Annotated[  # noqa: FBT002
        bool,
        typer.Option("--enabled", help="Show only enabled agents."),
    ] = False,
    disabled: Annotated[  # noqa: FBT002
        bool,
        typer.Option("--disabled", help="Show only disabled agents."),
    ] = False,
) -> None:
    """List available agents and their status.

    Examples:
        soothe agent list
        soothe agent list --enabled
        soothe agent list --disabled
    """
    from soothe.ux.cli.commands.status_cmd import agent_list

    agent_list(config=config, enabled=enabled, disabled=disabled)


@agent_app.command("status")
def _agent_status(
    config: Annotated[
        str | None,
        typer.Option("--config", "-c", help="Path to configuration file."),
    ] = None,
) -> None:
    """Show detailed agent status.

    Example:
        soothe agent status
    """
    from soothe.ux.cli.commands.status_cmd import agent_status

    agent_status(config=config)


# ---------------------------------------------------------------------------
# Health Check Command
# ---------------------------------------------------------------------------


@app.command("checkhealth")
def _checkhealth(
    config: Annotated[
        str | None,
        typer.Option("--config", "-c", help="Path to configuration file."),
    ] = None,
    output: Annotated[
        Literal["text", "json"],
        typer.Option("--output", "-o", help="Output format: text or json."),
    ] = "text",
    quiet: Annotated[  # noqa: FBT002
        bool,
        typer.Option("--quiet", "-q", help="Suppress output, return exit code only."),
    ] = False,
    categories: Annotated[
        list[str] | None,
        typer.Option("--check", help="Run specific checks (can be used multiple times)."),
    ] = None,
    exclude: Annotated[
        list[str] | None,
        typer.Option("--exclude", help="Exclude checks (can be used multiple times)."),
    ] = None,
    save_report: Annotated[
        str | None,
        typer.Option("--save-report", help="Save report to file (markdown format)."),
    ] = None,
) -> None:
    """Run comprehensive health checks.

    Validates configuration and checks backend service availability including
    PostgreSQL, LLM providers, vector stores, and external APIs.

    Exit codes: 0=OK, 1=warnings, 2=critical issues

    Examples:
        soothe checkhealth
        soothe checkhealth --output json
        soothe checkhealth --check daemon --check persistence
        soothe checkhealth --save-report report.md
    """
    from soothe.ux.cli.commands.health_cmd import checkhealth as _checkhealth_impl

    _checkhealth_impl(
        config=config,
        output=output,
        quiet=quiet,
        categories=categories,
        exclude=exclude,
        save_report=save_report,
    )


# ---------------------------------------------------------------------------
# Autopilot Command (Nested Subcommands)
# ---------------------------------------------------------------------------

autopilot_app = typer.Typer(name="autopilot", help="Run autonomous agent loops")
add_help_alias(autopilot_app)
app.add_typer(autopilot_app)


@autopilot_app.command("run")
def _autopilot_run(
    prompt: Annotated[
        str,
        typer.Argument(help="Task for autonomous execution."),
    ],
    config: Annotated[
        str | None,
        typer.Option("--config", "-c", help="Path to configuration file."),
    ] = None,
    max_iterations: Annotated[
        int | None,
        typer.Option("--max-iterations", help="Maximum autonomous iterations."),
    ] = None,
    output_format: Annotated[
        str,
        typer.Option("--format", "-f", help="Output format: text or jsonl."),
    ] = "text",
) -> None:
    """Run autonomous agent loop for complex tasks.

    Autopilot mode executes tasks autonomously without requiring user interaction.
    The agent will plan, execute, and iterate on the task until completion or
    reaching the maximum iteration limit.

    This mode is ideal for:
    - Long-running tasks that don't need user input
    - Background execution of complex workflows
    - Batch processing or research tasks
    - Automated testing and validation

    The agent operates in headless mode (no TUI) and outputs progress to stdout.
    Use --format jsonl for machine-readable output suitable for logging or piping.

    Examples:
        # Basic autonomous execution
        soothe autopilot run "Research AI safety and summarize findings"

        # Limit iterations for complex tasks
        soothe autopilot run "Build a web scraper" --max-iterations 10

        # Use custom config with JSON output
        soothe autopilot run "Analyze codebase" -c config.yml --format jsonl

        # Long-running research task
        soothe autopilot run "Investigate performance bottlenecks" --max-iterations 20
    """
    from soothe.ux.cli.commands.autopilot_cmd import autopilot as _autopilot

    _autopilot(
        prompt=prompt,
        config=config,
        max_iterations=max_iterations,
        output_format=output_format,
    )


# ---------------------------------------------------------------------------
# Help Command
# ---------------------------------------------------------------------------


@app.command(name="help")
def help_command(ctx: typer.Context) -> None:
    """Show help message and exit."""
    # Get the parent context (the main app) to show full help
    parent_ctx = ctx.parent or ctx
    typer.echo(parent_ctx.get_help())


if __name__ == "__main__":
    app()
