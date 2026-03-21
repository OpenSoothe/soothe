"""Autopilot command for autonomous execution."""

from typing import Annotated

import typer


def autopilot(
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
    """Run task in autonomous mode with iterative execution.

    Examples:
        soothe autopilot "Research AI safety"
        soothe autopilot "Build a tool" --max-iterations 10
    """
    from soothe.cli.commands.run_cmd import run_impl

    run_impl(
        prompt=prompt,
        config=config,
        thread_id=None,
        no_tui=True,
        autonomous=True,
        max_iterations=max_iterations,
        output_format=output_format,
        progress_verbosity=None,
    )
