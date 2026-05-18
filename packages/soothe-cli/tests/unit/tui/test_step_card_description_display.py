"""Step card title vs Explore row description display (IG-419)."""

from __future__ import annotations

from soothe_cli.tui.preview_limits import STEP_TASK_DELEGATION_DESC_MAX_CHARS
from soothe_cli.tui.tool_display import format_task_delegation_cli_command
from soothe_cli.tui.widgets.messages import CognitionStepMessage


def test_step_title_keeps_full_description() -> None:
    full = (
        "Find and analyze configuration files (pyproject.toml, setup.py, package.json, "
        "etc.) to understand project dependencies and build configuration"
    )
    step = CognitionStepMessage("IHD-01", full, id="step-full")
    assert step._description == full
    assert "chars abbr" not in step._description

    step.set_description(full + " — updated")
    assert step._description.endswith("updated")


def test_explore_row_truncates_description_tail() -> None:
    long_desc = "x" * (STEP_TASK_DELEGATION_DESC_MAX_CHARS + 40)
    line = format_task_delegation_cli_command(
        "explore",
        {"subagent_type": "explore", "description": long_desc},
    )
    assert long_desc not in line
    inner = line.split("Explore(", 1)[1]
    assert inner.endswith("…)") or inner.endswith("...)")
