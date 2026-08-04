"""Main CLI entry point using Typer."""

# Load environment variables from .env file BEFORE any langchain imports
# so provider API keys and other env-backed config are visible at import time.
from dotenv import load_dotenv

load_dotenv()

from pathlib import Path  # noqa: E402
from typing import Annotated  # noqa: E402

import click  # noqa: E402
import typer  # noqa: E402
from soothe_sdk.paths import SOOTHE_HOME  # noqa: E402

from soothe_cli.config.cli_config import CLIConfig  # noqa: E402
from soothe_cli.config.loader import set_runtime_config  # noqa: E402
from soothe_cli.tui._version import __version__  # noqa: E402
from soothe_cli.tui.markdown_theme import (  # noqa: E402
    DEFAULT_MARKDOWN_THEME,
    REGISTRY,
    load_markdown_theme_preference,
    markdown_theme_help,
)

# Make -h and --help equivalent everywhere (Click inherits this to nested cmds).
_HELP_OPTION_NAMES = ["-h", "--help"]

app = typer.Typer(
    name="soothe",
    help="Intelligent AI assistant for complex tasks.",
    no_args_is_help=False,
    add_completion=False,
    context_settings={"help_option_names": _HELP_OPTION_NAMES},
)


def _echo_help_for(base_ctx: click.Context, commands: list[str] | None) -> None:
    """Print help for ``base_ctx`` or a nested command path under it.

    Args:
        base_ctx: Context whose help is shown when ``commands`` is empty.
        commands: Optional path of subcommand names relative to ``base_ctx``.
    """
    if not commands:
        typer.echo(base_ctx.get_help())
        raise typer.Exit(code=0)

    current_cmd = base_ctx.command
    current_ctx = base_ctx
    for name in commands:
        # TyperGroup may not subclass click.Group; duck-type the MultiCommand API.
        get_command = getattr(current_cmd, "get_command", None)
        if get_command is None:
            typer.echo(
                f"Error: '{current_ctx.info_name}' has no subcommands.",
                err=True,
            )
            raise typer.Exit(code=2)
        next_cmd = get_command(current_ctx, name)
        if next_cmd is None:
            typer.echo(f"Error: No such command '{name}'.", err=True)
            raise typer.Exit(code=2)
        current_ctx = click.Context(next_cmd, info_name=name, parent=current_ctx)
        current_cmd = next_cmd
    typer.echo(current_ctx.get_help())
    raise typer.Exit(code=0)


def _register_help_command(typer_app: typer.Typer) -> None:
    """Register a ``help`` subcommand equivalent to ``-h`` / ``--help``."""

    @typer_app.command("help")
    def help_cmd(
        ctx: typer.Context,
        commands: Annotated[
            list[str] | None,
            typer.Argument(help="Optional subcommand path (e.g. list)."),
        ] = None,
    ) -> None:
        """Show this message and exit."""
        _echo_help_for(ctx.parent or ctx, commands)


def configure_command_group(
    nested_app: typer.Typer,
    *,
    show_help_on_no_args: bool = True,
) -> None:
    """Make ``-h``, ``--help``, and ``help`` equivalent for a nested group.

    ``-h`` / ``--help`` come from the root app's ``help_option_names`` (inherited
    by Click contexts). This registers a matching ``help`` subcommand and,
    optionally, prints help when the group is invoked with no subcommand.

    Args:
        nested_app: Nested Typer app to configure.
        show_help_on_no_args: When True, bare group invocation prints help
            (same as ``-h``). Set False when the group has its own default
            action or already sets ``no_args_is_help``.
    """
    if show_help_on_no_args:

        @nested_app.callback(invoke_without_command=True)
        def _no_args_help(ctx: typer.Context) -> None:
            if ctx.invoked_subcommand is None:
                typer.echo(ctx.get_help())
                raise typer.Exit(code=0)

    _register_help_command(nested_app)


# Backwards-compatible alias used by older call sites / tests.
add_help_alias = configure_command_group


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
        typer.Option("--streaming-mode", help="Streaming mode: 'streaming' or 'batch'."),
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
                "Composer mode: 'manual' (relay AI questions to you), "
                "'auto' (veritas auto-answers), or 'plan' (sticky planner "
                "routing without typing /plan). Default: 'manual' when stdin "
                "is a TTY, 'auto' otherwise."
            ),
        ),
    ] = None,
    auto_resume: Annotated[
        bool,
        typer.Option(
            "--auto-resume/--no-auto-resume",
            help=(
                "Auto-resume an active loop on startup without prompting. "
                "Default: prompt ([Enter] to resume / n to discard)."
            ),
        ),
    ] = False,
    plan_panel: Annotated[
        bool,
        typer.Option(
            "--plan-panel/--no-plan-panel",
            help=(
                "Auto-show the in-flow plan panel when a goal plan is active. "
                "Ctrl+t toggles thereafter. Default: disabled."
            ),
        ),
    ] = False,
    show_version: Annotated[  # noqa: FBT002
        bool,
        typer.Option("--version", help="Show version and exit."),
    ] = False,
) -> None:
    """Soothe CLI — intelligent AI assistant client.

    Run without arguments for interactive TUI mode, or pass --prompt for a one-shot
    headless query (stdout, then exit).

    Note: This is the CLI client. Use 'soothed' to manage the daemon server.

    Examples:
        soothe                           # Interactive TUI mode
        soothe -p "Research AI advances" # One-shot headless (non-TUI) query
        soothe -p "Hello" --tui         # TUI with an auto-submitted prompt
        soothe --daemon-port 9000 loop list  # Subcommands inherit global flags
        soothe loop list                 # List StrangeLoop instances
        soothe help loop                 # Same as: soothe loop --help
    """
    if show_version:
        typer.echo(f"soothe {__version__}")
        raise typer.Exit

    home_path = Path(soothe_home).expanduser() if soothe_home else Path(SOOTHE_HOME)
    if mode is not None and mode not in ("manual", "auto", "plan"):
        typer.echo(
            f"Invalid --mode {mode!r}; expected 'manual', 'auto', or 'plan'.",
            err=True,
        )
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
        auto_resume=auto_resume,
        plan_panel_default_visible=plan_panel,
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

for _sub_app, _name in (
    (_loop_app, "loop"),
    (_autopilot_app, "autopilot"),
    (_cron_app, "cron"),
    (_config_app, "config"),
):
    configure_command_group(_sub_app, show_help_on_no_args=True)
    app.add_typer(_sub_app, name=_name)

# status has a custom default action (combined status) — keep it; add help only.
configure_command_group(_status_app, show_help_on_no_args=False)
app.add_typer(_status_app, name="status")


# ---------------------------------------------------------------------------
# Help Command (same meaning as -h / --help; optional topic path)
# ---------------------------------------------------------------------------


@app.command(name="help")
def help_command(
    ctx: typer.Context,
    commands: Annotated[
        list[str] | None,
        typer.Argument(help="Optional command path (e.g. loop, loop list, autopilot top)."),
    ] = None,
) -> None:
    """Show this message and exit."""
    _echo_help_for(ctx.parent or ctx, commands)


if __name__ == "__main__":
    app()
