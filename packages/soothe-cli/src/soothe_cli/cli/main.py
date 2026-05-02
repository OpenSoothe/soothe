"""Main CLI entry point using Typer."""

# Load environment variables from .env file BEFORE any langchain imports
# This is required for LangSmith tracing to be activated at import time
from dotenv import load_dotenv

load_dotenv()

from importlib.metadata import version  # noqa: E402
from typing import Annotated  # noqa: E402

import typer  # noqa: E402

app = typer.Typer(
    name="soothe",
    help="Intelligent AI assistant for complex tasks",
    no_args_is_help=False,
    add_completion=False,
)


def add_help_alias(nested_app: typer.Typer) -> None:
    """Add -h as an alias for --help to a nested Typer app.

    This is a workaround for Typer not supporting -h for nested command groups.
    Must be called AFTER creating the nested app but BEFORE adding commands.

    Args:
        nested_app: The nested Typer app to add -h support to.
    """

    # Add a callback that defines -h option
    @nested_app.callback(invoke_without_command=True)
    def help_callback(
        ctx: typer.Context,
        show_help: Annotated[  # noqa: FBT002
            bool,
            typer.Option("-h", "--help", is_flag=True, help="Show this message and exit."),
        ] = False,
    ) -> None:
        # If -h/--help is passed, show help and exit before command parsing
        if show_help:
            typer.echo(ctx.get_help())
            raise typer.Exit(code=0)

        # If no subcommand and no help flag, show help by default
        if ctx.invoked_subcommand is None:
            typer.echo(ctx.get_help())
            raise typer.Exit(code=0)


@app.callback(invoke_without_command=True)
def main(
    ctx: typer.Context,
    prompt: Annotated[
        str | None,
        typer.Option(
            "--prompt", "-p", help="Prompt to send as user message (headless single-shot mode)."
        ),
    ] = None,
    no_tui: Annotated[  # noqa: FBT002
        bool,
        typer.Option("--no-tui", help="Disable TUI; run single prompt and exit."),
    ] = False,
    streaming: Annotated[
        bool | None,
        typer.Option("--streaming/--no-streaming", help="Enable/disable output streaming."),
    ] = None,
    streaming_mode: Annotated[
        str | None,
        typer.Option("--streaming-mode", help="Streaming mode: 'streaming' or 'batch'"),
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
    """Soothe CLI - Intelligent AI assistant client.

    Run without arguments for interactive TUI mode, or provide a prompt via --prompt/-p option.

    Note: This is the CLI client. Use 'soothed' command to manage the daemon server.

    Examples:
        soothe                           # Interactive TUI mode
        soothe -p "Research AI advances" # Headless single-prompt mode
        soothe loop list                 # List AgentLoop instances
    """
    # Handle -h/--help flag
    if show_help:
        typer.echo(ctx.get_help())
        raise typer.Exit

    # Handle --version flag
    if show_version:
        typer.echo(f"soothe {version('soothe-cli')}")
        raise typer.Exit

    # Only run default behavior if no subcommand is being invoked
    if ctx.invoked_subcommand is None:
        from soothe_cli.cli.commands.run_cmd import run_impl

        run_impl(
            prompt=prompt,
            thread_id=None,
            no_tui=no_tui,
            autonomous=False,
            max_iterations=None,
            streaming_enabled=streaming,
            streaming_mode=streaming_mode,
        )


# ---------------------------------------------------------------------------
# Sub-command groups (nested Typer apps)
# ---------------------------------------------------------------------------
# Thread: read-only diagnostics per RFC-503 (Loop-First UX). Lifecycle
# management lives under `soothe loop <subcommand>`.

from soothe_cli.cli.commands.autopilot_cmd import app as _autopilot_app  # noqa: E402
from soothe_cli.cli.commands.loop_cmd import loop_app as _loop_app  # noqa: E402
from soothe_cli.cli.commands.thread_cmd import thread_app as _thread_app  # noqa: E402

for _sub_app, _name in (
    (_thread_app, "thread"),
    (_loop_app, "loop"),
    (_autopilot_app, "autopilot"),
):
    add_help_alias(_sub_app)
    app.add_typer(_sub_app, name=_name)


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
