"""Tests for CLI -h / --help / help equivalence across command groups."""

from __future__ import annotations

import re

import pytest
from typer.testing import CliRunner

from soothe_cli.cli.main import app

runner = CliRunner()

# Groups where bare invocation and help should print the group help page.
_HELP_GROUPS = ("loop", "autopilot", "cron", "config")

# Leaf commands that previously only accepted --help (not -h).
_LEAF_HELPS = (
    ("loop", "list"),
    ("loop", "continue"),
    ("autopilot", "top"),
    ("autopilot", "status"),
    ("cron", "list"),
    ("config", "reload"),
    ("status", "daemon"),
)


# ANSI escape sequence pattern
_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


def _strip_ansi(text: str) -> str:
    """Remove ANSI escape sequences from text."""
    return _ANSI_RE.sub("", text)


def _usage_line(output: str) -> str:
    """Extract the Usage line from help output, stripping ANSI codes."""
    for line in output.splitlines():
        stripped = _strip_ansi(line.strip())
        # "Usage:" may appear mid-line after ANSI codes are stripped
        if "Usage:" in stripped:
            return stripped
    return ""


@pytest.mark.parametrize("flag", ["--help", "-h", "help"])
def test_root_help_variants_match(flag: str) -> None:
    """soothe --help, -h, and help show the same root usage page."""
    result = runner.invoke(app, [flag])
    assert result.exit_code == 0
    # Check usage line without ANSI codes
    assert "Usage:" in result.output and "soothe" in _usage_line(result.output)
    assert "--prompt" in result.output or "-prompt" in result.output


@pytest.mark.parametrize("group", _HELP_GROUPS)
@pytest.mark.parametrize("flag", ["--help", "-h", "help"])
def test_group_help_variants_match(group: str, flag: str) -> None:
    """Group -h, --help, and help are equivalent."""
    via_flag = runner.invoke(app, [group, flag])
    via_topic = runner.invoke(app, ["help", group])
    assert via_flag.exit_code == 0, via_flag.output
    assert via_topic.exit_code == 0, via_topic.output
    assert _usage_line(via_flag.output) == _usage_line(via_topic.output)
    # Check usage line without ANSI codes
    usage_line = _usage_line(via_flag.output)
    assert "Usage:" in usage_line and group in usage_line


@pytest.mark.parametrize("group", _HELP_GROUPS)
def test_group_bare_invocation_shows_help(group: str) -> None:
    """Bare group invocation shows help (same as -h) for help-default groups."""
    bare = runner.invoke(app, [group])
    flagged = runner.invoke(app, [group, "-h"])
    assert bare.exit_code == 0, bare.output
    assert flagged.exit_code == 0, flagged.output
    assert _usage_line(bare.output) == _usage_line(flagged.output)


@pytest.mark.parametrize(("group", "cmd"), _LEAF_HELPS)
@pytest.mark.parametrize("flag", ["--help", "-h"])
def test_leaf_short_and_long_help(group: str, cmd: str, flag: str) -> None:
    """Leaf commands accept both -h and --help."""
    result = runner.invoke(app, [group, cmd, flag])
    assert result.exit_code == 0, result.output
    # Check usage line without ANSI codes
    usage_line = _usage_line(result.output)
    assert "Usage:" in usage_line and group in usage_line and cmd in usage_line


@pytest.mark.parametrize(("group", "cmd"), _LEAF_HELPS)
def test_help_topic_path_matches_leaf_help(group: str, cmd: str) -> None:
    """soothe help <group> <cmd> matches soothe <group> <cmd> --help."""
    via_help = runner.invoke(app, ["help", group, cmd])
    via_flag = runner.invoke(app, [group, cmd, "--help"])
    assert via_help.exit_code == 0, via_help.output
    assert via_flag.exit_code == 0, via_flag.output
    assert _usage_line(via_help.output) == _usage_line(via_flag.output)


def test_nested_help_subcommand_path() -> None:
    """soothe loop help list matches soothe loop list --help."""
    via_nested = runner.invoke(app, ["loop", "help", "list"])
    via_flag = runner.invoke(app, ["loop", "list", "--help"])
    assert via_nested.exit_code == 0, via_nested.output
    assert via_flag.exit_code == 0, via_flag.output
    assert _usage_line(via_nested.output) == _usage_line(via_flag.output)


def test_status_help_variants_match() -> None:
    """status -h/--help/help show the status group page (bare status still runs)."""
    via_h = runner.invoke(app, ["status", "-h"])
    via_help = runner.invoke(app, ["status", "help"])
    via_long = runner.invoke(app, ["status", "--help"])
    assert via_h.exit_code == 0
    assert via_help.exit_code == 0
    assert via_long.exit_code == 0
    assert _usage_line(via_h.output) == _usage_line(via_help.output)
    assert _usage_line(via_h.output) == _usage_line(via_long.output)
    # Check usage line without ANSI codes
    usage_line = _usage_line(via_h.output)
    assert "Usage:" in usage_line and "status" in usage_line


def test_help_unknown_command_exits_2() -> None:
    result = runner.invoke(app, ["help", "not-a-real-command"])
    assert result.exit_code == 2
    assert "No such command" in result.output


def test_alias_help_has_no_double_backticks() -> None:
    """Command summaries should not render ReST double-backticks."""
    result = runner.invoke(app, ["autopilot", "--help"])
    assert result.exit_code == 0
    assert "``" not in result.output
    result = runner.invoke(app, ["loop", "--help"])
    assert result.exit_code == 0
    assert "``" not in result.output
