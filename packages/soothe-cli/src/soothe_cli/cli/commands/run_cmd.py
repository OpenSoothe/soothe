"""Run command for Soothe CLI."""

import logging
import sys
import time
from pathlib import Path
from typing import Any

import typer
from soothe_sdk.paths import SOOTHE_HOME
from soothe_sdk.utils.logging import resolve_cli_log_level

from soothe_cli.cli.execution import run_headless, run_tui
from soothe_cli.runtime import load_config, setup_logging

logger = logging.getLogger(__name__)


def run_impl(
    prompt: str | None,
    resume_loop_id: str | None,
    no_tui: bool,  # noqa: FBT001
    autonomous: bool,  # noqa: FBT001
    max_iterations: int | None,
    *,
    tui_with_prompt: bool = False,
    mcp_config: str | None = None,
) -> None:
    """Core implementation for running Soothe agent.

    Args:
        prompt: Optional user message; non-empty prompt defaults to a headless
            one-shot run unless ``tui_with_prompt`` is set or a loop is being
            resumed (``resume_loop_id``).
        resume_loop_id: Existing loop id to attach to (optional)
        no_tui: Require headless mode (must include a non-empty prompt)
        autonomous: Enable autonomous iteration mode
        max_iterations: Max iterations for autonomous mode
        tui_with_prompt: When True with a prompt, open the TUI instead of headless.
        mcp_config: Path to additional MCP server config (JSON/YAML) to merge.
    """
    startup_start = time.perf_counter()
    use_headless: bool | None = None  # Track execution mode for exit tip

    try:
        cfg = load_config()

        # Merge --mcp-config file into SootheConfig.mcp_servers
        if mcp_config:
            _merge_mcp_config(cfg, mcp_config)
        log_level = resolve_cli_log_level(logging_level=cfg.logging_level)
        log_file = Path(SOOTHE_HOME) / "logs" / "cli.log"
        setup_logging(log_level, log_file=log_file)

        # PostgreSQL availability check (requires daemon-side config)
        if hasattr(cfg, "protocols") and hasattr(cfg.protocols, "durability"):
            checkpointer = getattr(cfg.protocols.durability, "checkpointer", None)
            if checkpointer == "postgresql":
                logger.info("PostgreSQL checkpointer configured; ensure server is running.")

        startup_elapsed_ms = (time.perf_counter() - startup_start) * 1000
        logger.info("[Startup] ✓ Ready (%.1fms)", startup_elapsed_ms)

        run_start = time.perf_counter()

        has_prompt = bool(prompt and str(prompt).strip())
        attaching_loop = bool(resume_loop_id and str(resume_loop_id).strip())

        if tui_with_prompt and has_prompt:
            use_headless = False
        elif no_tui and not has_prompt:
            typer.echo(
                "Error: --no-tui requires a non-empty --prompt (-p).",
                err=True,
            )
            sys.exit(1)
        elif no_tui:
            use_headless = True
        else:
            use_headless = has_prompt and not attaching_loop

        if use_headless:
            run_headless(
                cfg,
                str(prompt).strip(),
                resume_loop_id=resume_loop_id,
                autonomous=autonomous,
                max_iterations=max_iterations,
            )
        else:
            run_tui(cfg, resume_loop_id=resume_loop_id, initial_prompt=prompt)

        run_elapsed_s = time.perf_counter() - run_start
        typer.echo(f"Total running time: {run_elapsed_s:.2f}s", err=True)

        # Show tip to continue the loop after TUI exits normally
        if use_headless is False:
            from soothe_cli.cli.execution.launcher import get_last_app_result

            result = get_last_app_result()
            if result is not None and result.loop_id:
                typer.echo(
                    f"💡 To continue: soothe loop resume {result.loop_id}",
                    err=True,
                )

    except KeyboardInterrupt:
        typer.echo("\nInterrupted. (daemon query cancelled)")
        # Also show loop continuation tip on Ctrl+C exit
        if use_headless is False:
            from soothe_cli.cli.execution.launcher import get_last_app_result

            result = get_last_app_result()
            if result is not None and result.loop_id:
                typer.echo(
                    f"💡 To continue: soothe loop resume {result.loop_id}",
                    err=True,
                )
        sys.exit(130)
    except Exception as e:
        logger.exception("CLI run error")
        from soothe_sdk.utils import format_cli_error

        typer.echo(f"Error: {format_cli_error(e)}", err=True)
        sys.exit(1)


def _merge_mcp_config(cfg: Any, mcp_config_path: str) -> None:
    """Load MCP server config from a JSON/YAML file and merge into SootheConfig.

    Args:
        cfg: SootheConfig instance.
        mcp_config_path: Path to MCP config file (JSON or YAML).
    """
    import json

    path = Path(mcp_config_path).expanduser().resolve()
    if not path.is_file():
        typer.echo(f"--mcp-config: file not found: {path}", err=True)
        return

    try:
        raw = path.read_text(encoding="utf-8")
        if path.suffix in (".yml", ".yaml"):
            try:
                import yaml

                data = yaml.safe_load(raw)
            except ImportError:
                typer.echo("--mcp-config: PyYAML not installed; use JSON format", err=True)
                return
        else:
            data = json.loads(raw)
    except Exception as e:
        typer.echo(f"--mcp-config: failed to parse {path}: {e}", err=True)
        return

    servers = data.get("mcp_servers") or data.get("servers") or []
    if not isinstance(servers, list):
        typer.echo("--mcp-config: expected 'mcp_servers' or 'servers' list", err=True)
        return

    from soothe.config.models import MCPServerConfig

    new_servers: list[MCPServerConfig] = []
    for entry in servers:
        if isinstance(entry, dict):
            try:
                new_servers.append(MCPServerConfig(**entry))
            except Exception as e:
                logger.warning("Skipping invalid MCP server entry: %s", e)

    if new_servers:
        existing = list(cfg.mcp_servers) if cfg.mcp_servers else []
        existing_names = {s.name for s in existing}
        for s in new_servers:
            if s.name in existing_names:
                logger.warning("--mcp-config: server '%s' already in config, skipping", s.name)
            else:
                existing.append(s)
        cfg.mcp_servers = existing
        logger.info("--mcp-config: merged %d MCP server(s)", len(new_servers))
