"""Main CLI entry point using Typer."""

# Load environment variables from .env file BEFORE any langchain imports
# so provider API keys and other env-backed config are visible at import time.
from dotenv import load_dotenv

load_dotenv()

from pathlib import Path  # noqa: E402
from typing import Annotated  # noqa: E402

import typer  # noqa: E402
from soothe_sdk.client.config import SOOTHE_HOME  # noqa: E402

from soothe_cli.tui._version import __version__  # noqa: E402

from soothe_cli.config.cli_config import CLIConfig  # noqa: E402
from soothe_cli.config.loader import set_runtime_config  # noqa: E402
from soothe_cli.tui.markdown_theme import (  # noqa: E402
    DEFAULT_MARKDOWN_THEME,
    REGISTRY,
    load_markdown_theme_preference,
    markdown_theme_help,
)

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
            "--prompt",
            "-p",
            help="User message; runs a one-shot headless query by default (use --tui for TUI).",
        ),
    ] = None,
    no_tui: Annotated[  # noqa: FBT002
        bool,
        typer.Option(
            "--no-tui",
            help="Headless mode (requires --prompt). Same as default when -p is set.",
        ),
    ] = False,
    tui_with_prompt: Annotated[  # noqa: FBT002
        bool,
        typer.Option(
            "--tui",
            help="With --prompt/-p, open the interactive TUI and auto-submit the prompt.",
        ),
    ] = False,
    daemon_host: Annotated[
        str,
        typer.Option("--daemon-host", help="Daemon WebSocket host."),
    ] = "127.0.0.1",
    daemon_port: Annotated[
        int,
        typer.Option("--daemon-port", help="Daemon WebSocket port."),
    ] = 8765,
    log_level: Annotated[
        str | None,
        typer.Option(
            "--log-level",
            help="CLI log level (DEBUG, INFO, …). SOOTHE_LOG_LEVEL env overrides.",
        ),
    ] = None,
    render_markdown: Annotated[
        bool,
        typer.Option(
            "--render-markdown/--no-render-markdown",
            help="Render assistant messages as Markdown in the TUI.",
        ),
    ] = True,
    markdown_theme: Annotated[
        str | None,
        typer.Option(
            "--markdown-theme",
            help=(
                "Markdown appearance preset for TUI cards "
                f"({markdown_theme_help()}). Default: {DEFAULT_MARKDOWN_THEME}."
            ),
        ),
    ] = None,
    soothe_home: Annotated[
        str | None,
        typer.Option("--soothe-home", help="Soothe home directory (default: ~/.soothe)."),
    ] = None,
    streaming: Annotated[
        bool | None,
        typer.Option("--streaming/--no-streaming", help="Enable/disable output streaming."),
    ] = None,
    streaming_mode: Annotated[
        str | None,
        typer.Option("--streaming-mode", help="Streaming mode: 'streaming' or 'batch'"),
    ] = None,
    mcp_config: Annotated[
        str | None,
        typer.Option(
            "--mcp-config",
            help="Path to additional MCP server config (JSON/YAML) to merge into daemon config.",
        ),
    ] = None,
    mode: Annotated[
        str | None,
        typer.Option(
            "--mode",
            help=(
                "Clarification mode: 'manual' (relay AI questions to you) or "
                "'auto' (veritas auto-answers). Default: 'manual' when stdin is "
                "a TTY, 'auto' otherwise."
            ),
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
    """Soothe CLI - Intelligent AI assistant client.

    Run without arguments for interactive TUI mode, or pass --prompt for a one-shot
    headless query (stdout, then exit).

    Note: This is the CLI client. Use 'soothed' command to manage the daemon server.

    Examples:
        soothe                           # Interactive TUI mode
        soothe -p "Research AI advances" # One-shot headless (non-TUI) query
        soothe -p "Hello" --tui         # TUI with an auto-submitted prompt
        soothe --daemon-port 9000 loop list  # Subcommands inherit global flags
        soothe loop list                 # List StrangeLoop instances
    """
    # Handle -h/--help flag
    if show_help:
        typer.echo(ctx.get_help())
        raise typer.Exit

    # Handle --version flag
    if show_version:
        typer.echo(f"soothe {__version__}")
        raise typer.Exit

    home_path = Path(soothe_home).expanduser() if soothe_home else Path(SOOTHE_HOME)
    if mode is not None and mode not in ("manual", "auto"):
        typer.echo(f"Invalid --mode {mode!r}; expected 'manual' or 'auto'.", err=True)
        raise typer.Exit(code=2)
    if markdown_theme is not None and markdown_theme not in REGISTRY:
        typer.echo(
            f"Invalid --markdown-theme {markdown_theme!r}; "
            f"expected one of: {markdown_theme_help()}.",
            err=True,
        )
        raise typer.Exit(code=2)
    resolved_markdown_theme = (
        markdown_theme if markdown_theme is not None else load_markdown_theme_preference()
    )
    cli_cfg = CLIConfig(
        daemon_host=daemon_host,
        daemon_port=daemon_port,
        logging_level=log_level,
        render_markdown=render_markdown,
        markdown_theme=resolved_markdown_theme,
        output_streaming_enabled=streaming,
        output_streaming_mode=streaming_mode,
        clarification_mode=mode,
        soothe_home=home_path,
    )
    set_runtime_config(cli_cfg)
    ctx.obj = cli_cfg

    # Only run default behavior if no subcommand is being invoked
    if ctx.invoked_subcommand is None:
        from soothe_cli.cli.commands.run_cmd import run_impl

        run_impl(
            prompt=prompt,
            resume_loop_id=None,
            no_tui=no_tui,
            autonomous=False,
            max_iterations=None,
            tui_with_prompt=tui_with_prompt,
            mcp_config=mcp_config,
        )


# ---------------------------------------------------------------------------
# Sub-command groups (nested Typer apps)
# ---------------------------------------------------------------------------

from soothe_cli.cli.commands.autopilot_cmd import app as _autopilot_app  # noqa: E402
from soothe_cli.cli.commands.config_cmd import config_app as _config_app  # noqa: E402
from soothe_cli.cli.commands.cron_cmd import app as _cron_app  # noqa: E402
from soothe_cli.cli.commands.loop_cmd import loop_app as _loop_app  # noqa: E402
from soothe_cli.cli.commands.status_cmd import status_app as _status_app  # noqa: E402

# status_app has custom default behavior (shows combined status), skip add_help_alias
for _sub_app, _name in (
    (_loop_app, "loop"),
    (_autopilot_app, "autopilot"),
    (_cron_app, "cron"),
    (_config_app, "config"),
):
    add_help_alias(_sub_app)
    app.add_typer(_sub_app, name=_name)

# status_app has its own callback for default behavior
app.add_typer(_status_app, name="status")


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
